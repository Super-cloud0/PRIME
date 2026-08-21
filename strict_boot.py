from __future__ import annotations

import base64
import json
import os
import uuid

import server
import server_prod
from flask import jsonify, request


STRICT_PROMPT = r'''You are PRIME's strict visual self-improvement evaluator.

Analyze ONLY visible, non-sensitive presentation features in the supplied photo. Never identify the person and never infer or mention age, race, ethnicity, religion, health, disability, sexual orientation, or other sensitive traits. Do not diagnose or sexualize.

The purpose is calibration, not encouragement. Do NOT be nice for the sake of being nice. Do NOT inflate scores. Judge only what is actually visible in this exact image.

Use this calibration literally:
0-19 = extremely weak visible presentation or unusable image.
20-29 = very weak, many obvious visible problems.
30-39 = clearly below average.
40-49 = somewhat below average.
50-59 = ordinary/average.
60-69 = clearly above average.
70-79 = strong and uncommon.
80-89 = exceptional and polished.
90-94 = extremely exceptional and rare.
95-100 = extraordinarily rare; almost never appropriate.

Rules:
- Average-looking presentations MUST stay around 45-60.
- Do not give 70+ merely because the person is pleasant-looking, young-looking, has clear lighting, or has one strong feature.
- Do not give 80+ unless almost every visible dimension is strong.
- Do not give 90+ unless the image shows an unusually consistent, exceptional result across essentially every visible dimension.
- A visible weakness must reduce its metric.
- If something cannot be judged reliably, use a neutral value rather than inventing a positive.
- Judge symmetry, proportion, grooming, hair, visible skin appearance, and overall presentation separately.
- The overall score returned by the model should be conservative; the server will independently compress it further.

Return ONLY JSON:
{"score":integer,"type":string,"summary":string,"metrics":{"symmetry":integer,"proportion":integer,"grooming":integer,"hair":integer,"skin_appearance":integer,"presentation":integer},"tips":[string],"confidence":integer}

All numeric fields are 0-100 integers. Give 3-5 direct, practical, safe improvement tips. If the face is not clearly visible, confidence <=20 and do not invent observations.'''


def strict_face_ai(user):
    data = request.get_json(silent=True) or {}
    image_b64 = data.get("image")
    if not image_b64 or not isinstance(image_b64, str):
        return jsonify({"error": "image is required"}), 400

    try:
        raw = base64.b64decode(image_b64, validate=True)
    except Exception:
        return jsonify({"error": "invalid image"}), 400
    if len(raw) > 8 * 1024 * 1024:
        return jsonify({"error": "image too large"}), 413

    try:
        result = server._gemini_json_compat(
            STRICT_PROMPT,
            base64.b64encode(raw).decode("ascii"),
            data.get("mime", "image/jpeg"),
        )

        allowed = {"symmetry", "proportion", "grooming", "hair", "skin_appearance", "presentation"}
        metrics = {}
        for key in allowed:
            value = (result.get("metrics") or {}).get(key)
            if isinstance(value, (int, float)):
                metrics[key] = max(0, min(100, int(value)))

        if not metrics:
            return jsonify({"error": "AI did not return usable metrics"}), 502

        # Never trust Gemini's headline score. Build the score from its individual
        # observations, then compress the result toward the true midpoint (50).
        # This is deliberately conservative so 70+ is uncommon and 80+ is rare.
        weights = {
            "symmetry": 0.22,
            "proportion": 0.22,
            "grooming": 0.15,
            "hair": 0.12,
            "skin_appearance": 0.14,
            "presentation": 0.15,
        }
        weighted = sum(metrics[k] * weights[k] for k in metrics)
        weight_total = sum(weights[k] for k in metrics)
        raw_score = weighted / weight_total

        # Compress distance from 50 by 25%. Examples: 60 -> 58, 70 -> 65,
        # 80 -> 73, 90 -> 80, 100 -> 88. This makes high scores genuinely rare.
        score = 50 + (raw_score - 50) * 0.75

        # Explicit penalty for weak dimensions. One strong feature cannot hide
        # several weak ones.
        weak = sum(1 for value in metrics.values() if value < 50)
        very_weak = sum(1 for value in metrics.values() if value < 40)
        score -= weak * 1.5
        score -= very_weak * 2.0

        # Hard ceilings prevent a single flattering output from reaching the top.
        if min(metrics.values()) < 55:
            score = min(score, 69)
        if sum(value >= 70 for value in metrics.values()) < 5:
            score = min(score, 74)
        if sum(value >= 80 for value in metrics.values()) < 5:
            score = min(score, 79)
        if sum(value >= 90 for value in metrics.values()) < 5:
            score = min(score, 89)

        score = max(10, min(95, round(score)))

        tips = [str(value)[:300] for value in (result.get("tips") or [])[:5]]
        try:
            confidence = max(0, min(100, int(result.get("confidence", 0))))
        except (TypeError, ValueError):
            confidence = 0

        analysis = server_prod.FaceAnalysis(
            id=str(uuid.uuid4()),
            user_id=user.id,
            score=score,
            analysis_type=str(result.get("type", "STRICT"))[:20],
            summary=str(result.get("summary", ""))[:2000],
            metrics_json=json.dumps(metrics),
            tips_json=json.dumps(tips),
            confidence=confidence,
        )
        user.prime_score = score
        server_prod.db.session.add(analysis)
        server_prod.db.session.commit()

        result.update({
            "score": score,
            "metrics": metrics,
            "tips": tips,
            "confidence": confidence,
            "analysis_id": analysis.id,
        })
        return jsonify(result)
    except Exception as exc:
        server_prod.db.session.rollback()
        server_prod.app.logger.exception("Strict Face AI analysis failed")
        return jsonify({"error": f"AI analysis failed: {type(exc).__name__}: {exc}"}), 502


# Render should serve this module so the strict endpoint wins over the
# compatibility endpoint installed by server.py.
app = server.app
server_prod.app.view_functions["face_ai"] = server_prod.auth_required(strict_face_ai)

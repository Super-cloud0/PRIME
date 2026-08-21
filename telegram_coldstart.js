// Render Free instances can take time to wake after inactivity.
// PRIME's existing app.js uses a 12s client timeout for API requests.
// Extend ONLY that exact timeout while leaving normal UI timers untouched.
(() => {
  const nativeSetTimeout = window.setTimeout.bind(window);
  window.setTimeout = (handler, delay, ...args) => {
    if (delay === 12000) delay = 75000;
    return nativeSetTimeout(handler, delay, ...args);
  };
})();

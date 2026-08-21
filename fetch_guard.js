(() => {
  const nativeFetch = window.fetch.bind(window);
  window.fetch = (input, init = {}) => {
    const controller = new AbortController();
    const callerSignal = init.signal;
    if (callerSignal) {
      if (callerSignal.aborted) controller.abort();
      else callerSignal.addEventListener('abort', () => controller.abort(), { once: true });
    }
    const timeout = setTimeout(() => controller.abort(), 90000);
    return nativeFetch(input, { ...init, signal: controller.signal }).finally(() => clearTimeout(timeout));
  };
})();

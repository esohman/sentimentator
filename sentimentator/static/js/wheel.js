(() => {
  const form = document.getElementById('annotation-form');
  if (!form) return;

  const stage = document.getElementById('wheel-stage');
  const image = document.getElementById('emotion-wheel');
  const markerLayer = document.getElementById('wheel-markers');
  const hidden = document.getElementById('wheel-points');
  const submissionIdInput = document.getElementById('submission-id');
  const rt = document.getElementById('rt-ms');
  const undoButton = document.getElementById('undo-point');
  const clearButton = document.getElementById('clear-points');
  const status = document.getElementById('selection-status');
  const coarseStatus = document.getElementById('coarse-status');
  const submit = document.getElementById('submit');
  const radios = [...form.querySelectorAll('input[name="sentiment"]')];
  const maxPoints = Number(stage.dataset.maxPoints || 8);
  const trialId = form.dataset.trialId;
  const storageKey = `emomap:trial:${trialId}`;

  let points = [];
  let activeMs = 0;
  let activeStartedAt = document.visibilityState === 'visible' ? performance.now() : null;
  let dirty = false;

  function makeSubmissionId() {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') {
      return window.crypto.randomUUID();
    }
    return `${Date.now()}-${Math.random().toString(16).slice(2)}-${Math.random().toString(16).slice(2)}`;
  }

  function currentActiveMs() {
    if (activeStartedAt === null) return activeMs;
    return activeMs + Math.max(0, performance.now() - activeStartedAt);
  }

  function snapshot() {
    const coarse = radios.find(r => r.checked)?.value || null;
    return {
      trialId,
      points,
      coarse,
      submissionId: submissionIdInput.value,
      activeMs: Math.round(currentActiveMs()),
      savedAt: Date.now(),
    };
  }

  function persist() {
    try {
      localStorage.setItem(storageKey, JSON.stringify(snapshot()));
    } catch (_) {
      // Annotation remains fully functional when localStorage is unavailable.
    }
  }

  function restore() {
    let saved = null;
    try {
      saved = JSON.parse(localStorage.getItem(storageKey) || 'null');
    } catch (_) {
      saved = null;
    }
    if (!saved || String(saved.trialId) !== String(trialId)) return;

    if (Array.isArray(saved.points)) {
      points = saved.points
        .filter(p => Number.isFinite(Number(p.x)) && Number.isFinite(Number(p.y)))
        .map(p => ({x: Number(p.x), y: Number(p.y)}))
        .filter(p => p.x >= 0 && p.x <= 1 && p.y >= 0 && p.y <= 1)
        .slice(0, maxPoints);
    }
    if (saved.coarse) {
      const radio = radios.find(r => r.value === saved.coarse);
      if (radio) radio.checked = true;
    }
    if (saved.submissionId) submissionIdInput.value = saved.submissionId;
    if (Number.isFinite(Number(saved.activeMs))) activeMs = Math.max(0, Number(saved.activeMs));
  }

  function renderMarkers() {
    markerLayer.replaceChildren();
    points.forEach((point, index) => {
      const marker = document.createElement('span');
      marker.className = 'wheel-marker';
      marker.textContent = String(index + 1);
      marker.style.left = `${point.x * 100}%`;
      marker.style.top = `${point.y * 100}%`;
      marker.dataset.pointIndex = String(index);
      markerLayer.appendChild(marker);
    });
  }

  function updateState({persistState = true} = {}) {
    hidden.value = JSON.stringify(points);
    renderMarkers();

    if (points.length === 0) status.textContent = `No associations selected (up to ${maxPoints})`;
    else if (points.length === 1) status.textContent = `1 association selected (up to ${maxPoints})`;
    else if (points.length < maxPoints) status.textContent = `${points.length} associations selected (up to ${maxPoints})`;
    else status.textContent = `${points.length} associations selected — maximum reached`;

    undoButton.disabled = points.length === 0;
    clearButton.disabled = points.length === 0;

    const coarseSelected = radios.some(r => r.checked);
    coarseStatus.textContent = coarseSelected ? 'Overall association selected.' : 'No overall association selected.';
    coarseStatus.classList.toggle('complete', coarseSelected);
    submit.disabled = points.length < 1 || !coarseSelected || form.dataset.submitting === '1';

    if (persistState) persist();
  }

  function pointFromEvent(event) {
    const rect = image.getBoundingClientRect();
    const x = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    const y = Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height));
    return {x: Number(x.toFixed(6)), y: Number(y.toFixed(6))};
  }

  stage.addEventListener('click', (event) => {
    if (event.target.closest('.wheel-marker')) return;
    if (points.length >= maxPoints) return;
    points.push(pointFromEvent(event));
    dirty = true;
    updateState();
  });

  // Right-clicking a numbered marker removes that association. Undo/Clear are
  // also provided so the interface remains usable on touch devices.
  markerLayer.addEventListener('contextmenu', (event) => {
    const marker = event.target.closest('.wheel-marker');
    if (!marker) return;
    event.preventDefault();
    const index = Number(marker.dataset.pointIndex);
    if (index >= 0 && index < points.length) {
      points.splice(index, 1);
      dirty = true;
      updateState();
    }
  });

  undoButton.addEventListener('click', () => {
    points.pop();
    dirty = true;
    updateState();
  });

  clearButton.addEventListener('click', () => {
    points = [];
    dirty = true;
    updateState();
  });

  radios.forEach(radio => radio.addEventListener('change', () => {
    dirty = true;
    updateState();
  }));

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden' && activeStartedAt !== null) {
      activeMs += Math.max(0, performance.now() - activeStartedAt);
      activeStartedAt = null;
      persist();
    } else if (document.visibilityState === 'visible' && activeStartedAt === null) {
      activeStartedAt = performance.now();
    }
  });

  window.addEventListener('beforeunload', (event) => {
    persist();
    if (dirty && form.dataset.submitting !== '1') {
      event.preventDefault();
      event.returnValue = '';
    }
  });

  form.addEventListener('submit', (event) => {
    const coarseSelected = radios.some(r => r.checked);
    if (points.length < 1 || !coarseSelected || form.dataset.submitting === '1') {
      event.preventDefault();
      updateState();
      return;
    }

    rt.value = Math.round(currentActiveMs()).toString();
    hidden.value = JSON.stringify(points);
    persist();
    form.dataset.submitting = '1';
    dirty = false;
    submit.disabled = true;
    submit.value = 'SAVING…';
  });

  if (!submissionIdInput.value) submissionIdInput.value = makeSubmissionId();
  restore();
  if (!submissionIdInput.value) submissionIdInput.value = makeSubmissionId();
  updateState({persistState: true});
})();

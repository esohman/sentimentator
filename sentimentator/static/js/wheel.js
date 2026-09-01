(() => {
  const form = document.getElementById('annotation-form');
  if (!form) return;

  const stage = document.getElementById('wheel-stage');
  const image = document.getElementById('emotion-wheel');
  const markerLayer = document.getElementById('wheel-markers');
  const hidden = document.getElementById('wheel-points');
  const rt = document.getElementById('rt-ms');
  const undoButton = document.getElementById('undo-point');
  const clearButton = document.getElementById('clear-points');
  const status = document.getElementById('selection-status');
  const coarseStatus = document.getElementById('coarse-status');
  const submit = document.getElementById('submit');
  const radios = [...form.querySelectorAll('input[name="sentiment"]')];
  const maxPoints = Number(stage.dataset.maxPoints || 8);

  const start = performance.now();
  let points = [];

  function renderMarkers() {
    markerLayer.replaceChildren();
    points.forEach((point, index) => {
      const marker = document.createElement('span');
      marker.className = 'wheel-marker';
      marker.textContent = String(index + 1);
      marker.style.left = `${point.x * 100}%`;
      marker.style.top = `${point.y * 100}%`;
      markerLayer.appendChild(marker);
    });
  }

  function updateState() {
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
    submit.disabled = points.length < 1 || !coarseSelected;
  }

  function pointFromEvent(event) {
    const rect = image.getBoundingClientRect();
    const x = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    const y = Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height));
    return {x: Number(x.toFixed(6)), y: Number(y.toFixed(6))};
  }

  stage.addEventListener('click', (event) => {
    if (event.target.closest('button')) return;
    if (points.length >= maxPoints) return;
    points.push(pointFromEvent(event));
    updateState();
  });

  // Right-clicking a numbered marker removes that association. We deliberately
  // do NOT encode a theoretical "reverse emotion" operation.
  markerLayer.addEventListener('contextmenu', (event) => {
    const marker = event.target.closest('.wheel-marker');
    if (!marker) return;
    event.preventDefault();
    const index = Number(marker.textContent) - 1;
    if (index >= 0 && index < points.length) {
      points.splice(index, 1);
      updateState();
    }
  });

  undoButton.addEventListener('click', () => { points.pop(); updateState(); });
  clearButton.addEventListener('click', () => { points = []; updateState(); });
  radios.forEach(radio => radio.addEventListener('change', updateState));

  form.addEventListener('submit', (event) => {
    const coarseSelected = radios.some(r => r.checked);
    if (points.length < 1 || !coarseSelected) {
      event.preventDefault();
      updateState();
      return;
    }
    rt.value = Math.round(performance.now() - start).toString();
  });

  updateState();
})();

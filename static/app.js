const recognizedKeys = [
  ["gross_weight", "毛重"],
  ["tare_weight", "皮重"],
  ["unit_price", "单价"],
  ["settlement_weight", "结算重量"],
  ["tax_fee", "税费"],
];

const LONG_PRESS_PAN_MS = 200;

const resultLabels = {
  scale_weight: "司磅重量",
  customer_service_fee: "客户手续费",
  customer_broker_fee: "客户中介费",
  factory_amount: "收厂钱",
  customer_amount: "转客户钱",
};

const state = {
  filename: "",
  imageBase64: "",
  fields: Object.fromEntries(recognizedKeys.map(([key, label]) => [key, { key, label, value: "", confidence: 0, source: "manual" }])),
  results: {},
  template: null,
  warnings: [],
  zoom: 1,
  fitZoom: 1,
  rotate: 0,
  offsetX: 0,
  offsetY: 0,
  naturalWidth: 0,
  naturalHeight: 0,
  longPressTimer: null,
  panPointerId: null,
  panStartX: 0,
  panStartY: 0,
  panning: false,
  lastPointerX: 0,
  lastPointerY: 0,
  needsCalculation: false,
};

const els = {
  serviceStatus: document.getElementById("serviceStatus"),
  ocrMode: document.getElementById("ocrMode"),
  templateSelect: document.getElementById("templateSelect"),
  fileInput: document.getElementById("fileInput"),
  recognizeBtn: document.getElementById("recognizeBtn"),
  fileName: document.getElementById("fileName"),
  previewImage: document.getElementById("previewImage"),
  emptyState: document.getElementById("emptyState"),
  viewerStage: document.getElementById("viewerStage"),
  zoomOutBtn: document.getElementById("zoomOutBtn"),
  zoomInBtn: document.getElementById("zoomInBtn"),
  zoomRange: document.getElementById("zoomRange"),
  fitViewBtn: document.getElementById("fitViewBtn"),
  actualSizeBtn: document.getElementById("actualSizeBtn"),
  rotateBtn: document.getElementById("rotateBtn"),
  resetViewBtn: document.getElementById("resetViewBtn"),
  fieldTable: document.getElementById("fieldTable"),
  serviceFee: document.getElementById("serviceFee"),
  brokerFee: document.getElementById("brokerFee"),
  calculateBtn: document.getElementById("calculateBtn"),
  resultsGrid: document.getElementById("resultsGrid"),
  templateName: document.getElementById("templateName"),
  recognizeStatus: document.getElementById("recognizeStatus"),
  warningList: document.getElementById("warningList"),
  exportJsonBtn: document.getElementById("exportJsonBtn"),
  exportCsvBtn: document.getElementById("exportCsvBtn"),
};

document.addEventListener("DOMContentLoaded", init);

async function init() {
  renderFields();
  renderResults();
  bindEvents();
  await Promise.all([loadHealth(), loadTemplates()]);
}

function bindEvents() {
  els.fileInput.addEventListener("change", async (event) => {
    const file = event.target.files[0];
    if (file) await loadFile(file);
  });
  els.recognizeBtn.addEventListener("click", recognizeCurrentImage);
  els.serviceFee.addEventListener("input", markNeedsCalculation);
  els.brokerFee.addEventListener("input", markNeedsCalculation);
  els.calculateBtn.addEventListener("click", recalculate);
  els.exportJsonBtn.addEventListener("click", exportJson);
  els.exportCsvBtn.addEventListener("click", exportCsv);

  els.zoomOutBtn.addEventListener("click", () => setZoom(state.zoom / 1.18));
  els.zoomInBtn.addEventListener("click", () => setZoom(state.zoom * 1.18));
  els.zoomRange.addEventListener("input", () => setZoom(Number(els.zoomRange.value) / 100));
  els.fitViewBtn.addEventListener("click", fitImageToStage);
  els.actualSizeBtn.addEventListener("click", showActualSize);
  els.viewerStage.addEventListener("wheel", handleImageWheel, { passive: false });
  els.viewerStage.addEventListener("pointerdown", startPan);
  els.viewerStage.addEventListener("pointermove", continuePan);
  els.viewerStage.addEventListener("pointerup", stopPan);
  els.viewerStage.addEventListener("pointercancel", stopPan);
  els.rotateBtn.addEventListener("click", () => {
    state.rotate = (state.rotate + 90) % 360;
    fitImageToStage();
  });
  els.resetViewBtn.addEventListener("click", resetView);

  window.addEventListener("resize", () => {
    if (state.imageBase64 && Math.abs(state.zoom - state.fitZoom) < 0.02) fitImageToStage();
    else updateImageTransform();
  });

}

async function loadHealth() {
  els.serviceStatus.textContent = "本地服务正常 · OCR 加载中（正在真实加载模型）";
  try {
    const data = await getJson("/api/v1/health");
    if (!data.ok) {
      els.serviceStatus.textContent = "服务异常";
      return;
    }
    if (data.ocr_ready === true) {
      const mode = data.is_frozen ? "便携版" : "源码服务";
      els.serviceStatus.textContent = `本地服务正常 · 本地 OCR 已就绪（模型已真实加载） · ${mode} · ${data.version}`;
    } else if (data.ocr_ready === false) {
      const reason = data.last_ocr_error || "请确认使用的是完整 dist\\orc-calc 文件夹，并且 .venv-ocr 没有被删除。";
      els.serviceStatus.textContent = `本地服务正常 · 本地 OCR 不可用 · ${data.version}`;
      showWarnings([
        `本地 OCR 不可用：${reason}`,
        data.ocr_cache_path ? `OCR 缓存目录：${data.ocr_cache_path}` : "",
      ]);
    } else {
      els.serviceStatus.textContent = `本地服务正常 · OCR 状态未知 · ${data.version}，请关闭旧服务后重新双击新版 EXE`;
      showWarnings(["当前网页可能连接到旧服务。请关闭旧的命令行窗口或旧的 python.exe 服务，再双击 dist\\orc-calc\\orc-calc.exe。"]);
    }
  } catch (error) {
    els.serviceStatus.textContent = "服务未连接";
  }
}

async function loadTemplates() {
  try {
    const data = await getJson("/api/v1/templates");
    for (const template of data.templates || []) {
      const option = document.createElement("option");
      option.value = template.id;
      option.textContent = template.name;
      els.templateSelect.appendChild(option);
    }
  } catch (error) {
    showWarnings([`模板加载失败：${error.message}`]);
  }
}

async function loadFile(file) {
  state.filename = file.name;
  state.imageBase64 = await fileToDataUrl(file);
  els.fileName.textContent = file.name;
  els.previewImage.onload = () => {
    state.naturalWidth = els.previewImage.naturalWidth || 1;
    state.naturalHeight = els.previewImage.naturalHeight || 1;
    els.previewImage.style.width = `${state.naturalWidth}px`;
    fitImageToStage();
  };
  els.previewImage.src = state.imageBase64;
  els.previewImage.style.display = "block";
  els.emptyState.style.display = "none";
  setStatus("待识别");
}

async function recognizeCurrentImage() {
  if (!state.imageBase64) {
    showWarnings(["请先上传图片。"]);
    return;
  }
  setStatus("识别中");
  try {
    const payload = {
      ocr: els.ocrMode.value,
      template_id: els.templateSelect.value,
      filename: state.filename,
      image_base64: state.imageBase64,
    };
    const data = await postJson("/api/v1/recognize", payload);
    applyRecognition(data);
    setStatus("已识别", "success");
  } catch (error) {
    setStatus("识别失败", "warning");
    showWarnings([error.message]);
  }
}

function applyRecognition(data) {
  state.template = data.template;
  state.warnings = data.warnings || [];
  for (const field of data.fields || []) {
    state.fields[field.key] = field;
  }
  state.results = data.calculation?.results || {};
  clearCalculationDirty();
  els.templateName.textContent = `模板：${state.template ? state.template.name : "未匹配"}`;
  renderFields();
  renderResults();
  showWarnings(state.warnings);
}

async function recalculate() {
  try {
    const data = await postJson("/api/v1/calculate", { values: collectValues() });
    state.results = data.results || {};
    renderResults();
    clearCalculationDirty();
  } catch (error) {
    showWarnings([`计算失败：${error.message}`]);
  }
}

function collectValues() {
  const values = {};
  for (const [key] of recognizedKeys) values[key] = state.fields[key]?.value || "";
  values.service_fee_per_ton = els.serviceFee.value || "0";
  values.broker_fee_per_ton = els.brokerFee.value || "0";
  return values;
}

function renderFields() {
  els.fieldTable.innerHTML = "";
  for (const [key, label] of recognizedKeys) {
    const field = state.fields[key] || { value: "", confidence: 0 };
    const row = document.createElement("div");
    row.className = "field-row";

    const labelEl = document.createElement("div");
    labelEl.className = "field-label";
    labelEl.textContent = label;

    const input = document.createElement("input");
    input.inputMode = "decimal";
    input.value = field.value || "";
    input.addEventListener("input", () => {
      state.fields[key] = { ...field, value: input.value, source: "manual" };
      markNeedsCalculation();
    });

    const confidence = Number(field.confidence || 0);
    const confidenceEl = document.createElement("div");
    confidenceEl.className = "confidence";
    confidenceEl.innerHTML = `
      <span>${field.source === "missing" ? "未识别" : `${Math.round(confidence * 100)}%`}</span>
      <div class="meter ${confidence && confidence < 0.75 ? "low" : ""}"><span style="width: ${Math.max(0, Math.min(100, confidence * 100))}%"></span></div>
    `;

    row.append(labelEl, input, confidenceEl);
    els.fieldTable.appendChild(row);
  }
}

function renderResults() {
  const keys = ["scale_weight", "factory_amount", "customer_amount", "customer_service_fee", "customer_broker_fee"];
  els.resultsGrid.innerHTML = "";
  for (const key of keys) {
    const item = document.createElement("div");
    item.className = `result-item ${key === "customer_amount" ? "primary" : ""}`;
    item.innerHTML = `<span>${resultLabels[key]}</span><strong>${state.results[key] ?? "0"}</strong>`;
    els.resultsGrid.appendChild(item);
  }
}

function showWarnings(warnings) {
  const list = warnings.filter(Boolean);
  if (!list.length) {
    els.warningList.hidden = true;
    els.warningList.innerHTML = "";
    return;
  }
  els.warningList.hidden = false;
  els.warningList.innerHTML = list.map((item) => `<div>${escapeHtml(item)}</div>`).join("");
}

function setStatus(text, tone = "") {
  els.recognizeStatus.textContent = text;
  els.recognizeStatus.className = `status-pill ${tone}`;
}

function fitImageToStage() {
  if (!state.naturalWidth || !state.naturalHeight) return;
  const rect = els.viewerStage.getBoundingClientRect();
  const rotated = state.rotate % 180 !== 0;
  const imageWidth = rotated ? state.naturalHeight : state.naturalWidth;
  const imageHeight = rotated ? state.naturalWidth : state.naturalHeight;
  const padding = 34;
  state.fitZoom = Math.max(0.05, Math.min((rect.width - padding) / imageWidth, (rect.height - padding) / imageHeight, 1));
  state.zoom = state.fitZoom;
  state.offsetX = 0;
  state.offsetY = 0;
  updateImageTransform();
}

function showActualSize() {
  state.zoom = 1;
  state.offsetX = 0;
  state.offsetY = 0;
  updateImageTransform();
}

function resetView() {
  state.rotate = 0;
  fitImageToStage();
}

function setZoom(value, origin = null) {
  if (!state.imageBase64) return;
  const oldZoom = state.zoom;
  const nextZoom = Math.max(0.05, Math.min(5, value));
  if (origin && oldZoom > 0) {
    const rect = els.viewerStage.getBoundingClientRect();
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;
    const pointerX = origin.clientX - centerX;
    const pointerY = origin.clientY - centerY;
    const ratio = nextZoom / oldZoom;
    state.offsetX = pointerX - (pointerX - state.offsetX) * ratio;
    state.offsetY = pointerY - (pointerY - state.offsetY) * ratio;
  }
  state.zoom = nextZoom;
  updateImageTransform();
}

function handleImageWheel(event) {
  if (!state.imageBase64) return;
  event.preventDefault();
  const factor = event.deltaY < 0 ? 1.14 : 1 / 1.14;
  setZoom(state.zoom * factor, event);
}

function startPan(event) {
  if (!state.imageBase64 || (event.pointerType === "mouse" && event.button !== 0)) return;
  event.preventDefault();
  clearPanTimer();
  state.panPointerId = event.pointerId;
  state.panStartX = event.clientX;
  state.panStartY = event.clientY;
  state.lastPointerX = event.clientX;
  state.lastPointerY = event.clientY;
  els.viewerStage.setPointerCapture(event.pointerId);
  els.viewerStage.classList.add("pan-ready");
  state.longPressTimer = window.setTimeout(() => {
    if (state.panPointerId !== event.pointerId) return;
    state.panning = true;
    state.lastPointerX = state.panStartX;
    state.lastPointerY = state.panStartY;
    els.viewerStage.classList.add("panning");
  }, LONG_PRESS_PAN_MS);
}

function continuePan(event) {
  if (state.panPointerId !== event.pointerId) return;
  if (!state.panning) {
    state.panStartX = event.clientX;
    state.panStartY = event.clientY;
    state.lastPointerX = event.clientX;
    state.lastPointerY = event.clientY;
    return;
  }
  state.offsetX += event.clientX - state.lastPointerX;
  state.offsetY += event.clientY - state.lastPointerY;
  state.lastPointerX = event.clientX;
  state.lastPointerY = event.clientY;
  updateImageTransform();
}

function stopPan(event) {
  if (state.panPointerId !== null && state.panPointerId !== event.pointerId) return;
  clearPanTimer();
  state.panning = false;
  state.panPointerId = null;
  try {
    els.viewerStage.releasePointerCapture(event.pointerId);
  } catch (_) {
    // Pointer capture may already be released by the browser.
  }
  els.viewerStage.classList.remove("pan-ready", "panning");
}

function clearPanTimer() {
  if (!state.longPressTimer) return;
  window.clearTimeout(state.longPressTimer);
  state.longPressTimer = null;
}

function updateImageTransform() {
  clampOffsets();
  els.zoomRange.value = Math.round(state.zoom * 100);
  els.previewImage.style.transform = `translate(${state.offsetX}px, ${state.offsetY}px) scale(${state.zoom}) rotate(${state.rotate}deg)`;
}

function clampOffsets() {
  if (!state.naturalWidth || !state.naturalHeight) return;
  const rect = els.viewerStage.getBoundingClientRect();
  const rotated = state.rotate % 180 !== 0;
  const width = (rotated ? state.naturalHeight : state.naturalWidth) * state.zoom;
  const height = (rotated ? state.naturalWidth : state.naturalHeight) * state.zoom;
  const minVisibleX = Math.min(96, Math.max(24, width * 0.3));
  const minVisibleY = Math.min(96, Math.max(24, height * 0.3));
  const limitX = Math.max(0, (rect.width + width) / 2 - minVisibleX);
  const limitY = Math.max(0, (rect.height + height) / 2 - minVisibleY);
  state.offsetX = Math.max(-limitX, Math.min(limitX, state.offsetX));
  state.offsetY = Math.max(-limitY, Math.min(limitY, state.offsetY));
}

function markNeedsCalculation() {
  state.needsCalculation = true;
  els.calculateBtn.classList.add("needs-calc");
}

function clearCalculationDirty() {
  state.needsCalculation = false;
  els.calculateBtn.classList.remove("needs-calc");
}

function exportJson() {
  const payload = {
    filename: state.filename,
    template: state.template,
    fields: Object.fromEntries(Object.entries(state.fields).map(([key, field]) => [key, field.value])),
    manual: {
      service_fee_per_ton: els.serviceFee.value || "0",
      broker_fee_per_ton: els.brokerFee.value || "0",
    },
    results: state.results,
    warnings: state.warnings,
  };
  download("orc-result.json", JSON.stringify(payload, null, 2), "application/json;charset=utf-8");
}

function exportCsv() {
  const rows = [["项目", "值"]];
  for (const [key, label] of recognizedKeys) rows.push([label, state.fields[key]?.value || ""]);
  rows.push(["手续费", els.serviceFee.value || "0"]);
  rows.push(["中介费", els.brokerFee.value || "0"]);
  for (const [key, label] of Object.entries(resultLabels)) rows.push([label, state.results[key] || "0"]);
  const csv = rows.map((row) => row.map(csvCell).join(",")).join("\n");
  download("orc-result.csv", `\ufeff${csv}`, "text/csv;charset=utf-8");
}

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok || data.ok === false) throw new Error(data.error || `${response.status} ${response.statusText}`);
  return data;
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

function download(filename, content, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function csvCell(value) {
  const text = String(value ?? "");
  if (/[",\n]/.test(text)) return `"${text.replace(/"/g, '""')}"`;
  return text;
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function isTypingTarget(target) {
  const tag = target?.tagName?.toLowerCase();
  return tag === "input" || tag === "textarea" || tag === "select" || target?.isContentEditable;
}

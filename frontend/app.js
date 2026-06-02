const TASK_STORAGE_KEY = "docker-mirror-recent-tasks";
const MAX_STORED_TASKS = 12;
const POLL_INTERVAL_MS = 2500;

const rootState = {
  apiBaseUrl: getApiBaseUrl(),
  tasks: loadStoredTasks(),
  images: [],
  pollTimer: null,
  isSubmitting: false,
  isRefreshingImages: false,
};

const elements = {
  apiEndpoint: document.querySelector("#api-endpoint"),
  connectionStatus: document.querySelector("#connection-status"),
  archiveTotalSize: document.querySelector("#archive-total-size"),
  archiveCount: document.querySelector("#archive-count"),
  lastImageRefresh: document.querySelector("#last-image-refresh"),
  pullForm: document.querySelector("#pull-form"),
  imageInput: document.querySelector("#image-input"),
  submitButton: document.querySelector("#submit-button"),
  refreshAllButton: document.querySelector("#refresh-all-button"),
  refreshImagesButton: document.querySelector("#refresh-images-button"),
  taskList: document.querySelector("#task-list"),
  cancelledTasksPanel: document.querySelector("#cancelled-tasks-panel"),
  cancelledTaskList: document.querySelector("#cancelled-task-list"),
  imageList: document.querySelector("#image-list"),
  toastRegion: document.querySelector("#toast-region"),
  summaryTotal: document.querySelector("#summary-total"),
  summaryRunning: document.querySelector("#summary-running"),
  summarySuccess: document.querySelector("#summary-success"),
  summaryFailed: document.querySelector("#summary-failed"),
};

bootstrap();

function bootstrap() {
  bindEvents();
  renderApiTarget();
  renderTasks();
  renderImages();
  refreshAll();
  rootState.pollTimer = window.setInterval(pollActiveTasks, POLL_INTERVAL_MS);
}

function bindEvents() {
  elements.pullForm.addEventListener("submit", handlePullSubmit);
  elements.refreshAllButton.addEventListener("click", refreshAll);
  elements.refreshImagesButton.addEventListener("click", refreshImages);

  document.querySelectorAll("[data-image]").forEach((button) => {
    button.addEventListener("click", () => {
      elements.imageInput.value = button.dataset.image || "";
      elements.imageInput.focus();
    });
  });
}

function getApiBaseUrl() {
  const configuredBase = window.DOCKER_MIRROR_CONFIG?.apiBaseUrl;
  if (configuredBase) {
    return normalizeApiBaseUrl(configuredBase);
  }

  if (window.location.protocol === "file:") {
    return "http://127.0.0.1:8000";
  }

  const isLocalPreview = ["127.0.0.1", "localhost"].includes(window.location.hostname);
  if (isLocalPreview && window.location.port !== "8000") {
    return `${window.location.protocol}//${window.location.hostname}:8000`;
  }

  return "";
}

function normalizeApiBaseUrl(value) {
  if (!value) {
    return "";
  }

  return value.endsWith("/") ? value.slice(0, -1) : value;
}

function loadStoredTasks() {
  try {
    const raw = window.localStorage.getItem(TASK_STORAGE_KEY);
    if (!raw) {
      return [];
    }

    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return [];
    }

    return parsed
      .filter((item) => item && typeof item.task_id === "string" && typeof item.image === "string")
      .slice(0, MAX_STORED_TASKS);
  } catch {
    return [];
  }
}

function persistTasks() {
  window.localStorage.setItem(
    TASK_STORAGE_KEY,
    JSON.stringify(rootState.tasks.slice(0, MAX_STORED_TASKS)),
  );
}

async function refreshAll() {
  await Promise.allSettled([checkApiHealth(), refreshImages(), pollActiveTasks(true)]);
}

async function checkApiHealth() {
  try {
    await apiFetch("/");
    elements.connectionStatus.textContent = "已连接";
    elements.connectionStatus.className = "status-success";
  } catch (error) {
    elements.connectionStatus.textContent = "连接失败";
    elements.connectionStatus.className = "status-failed";
    pushToast("连接失败", error.message, "error");
  }
}

async function handlePullSubmit(event) {
  event.preventDefault();
  if (rootState.isSubmitting) {
    return;
  }

  const image = elements.imageInput.value.trim();
  if (!image) {
    pushToast("镜像名为空", "请输入合法的 Docker 镜像名。", "error");
    return;
  }

  rootState.isSubmitting = true;
  elements.submitButton.disabled = true;
  elements.submitButton.textContent = "提交中...";

  try {
    const response = await apiFetch("/images/pull", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ image }),
    });

    upsertTask({
      task_id: response.task_id,
      image: response.image,
      status: response.status,
      filename: null,
      error: null,
      logs: ["任务已创建，等待后端开始处理。"],
      observed_at: new Date().toISOString(),
    });

    elements.imageInput.value = "";
    renderTasks();
    pushToast("任务已提交", `镜像 ${response.image} 已进入队列。`, "success");
    await pollSingleTask(response.task_id);
  } catch (error) {
    pushToast("提交失败", error.message, "error");
  } finally {
    rootState.isSubmitting = false;
    elements.submitButton.disabled = false;
    elements.submitButton.textContent = "开始拉取";
  }
}

async function refreshImages() {
  if (rootState.isRefreshingImages) {
    return;
  }

  rootState.isRefreshingImages = true;
  elements.refreshImagesButton.disabled = true;

  try {
    const response = await apiFetch("/images");
    rootState.images = Array.isArray(response.images) ? response.images : [];
    elements.lastImageRefresh.textContent = `最近刷新 ${formatDateTime(new Date().toISOString())}`;
    renderImages();
  } catch (error) {
    pushToast("归档刷新失败", error.message, "error");
  } finally {
    rootState.isRefreshingImages = false;
    elements.refreshImagesButton.disabled = false;
  }
}

async function pollActiveTasks(includeCompleted = false) {
  const tasksToRefresh = rootState.tasks.filter((task) => {
    if (includeCompleted) {
      return true;
    }

    return task.status === "pending" || task.status === "running";
  });

  if (tasksToRefresh.length === 0) {
    renderTasks();
    return;
  }

  await Promise.all(tasksToRefresh.map((task) => pollSingleTask(task.task_id, false)));
}

async function pollSingleTask(taskId, notifyOnError = true) {
  try {
    const response = await apiFetch(`/tasks/${encodeURIComponent(taskId)}`);
    const existingTask = rootState.tasks.find((task) => task.task_id === taskId);
    const previousStatus = existingTask?.status;
    upsertTask({
      ...response,
      observed_at: new Date().toISOString(),
    });

    if (previousStatus !== response.status) {
      if (response.status === "success") {
        pushToast("任务完成", `镜像 ${response.image} 已生成归档。`, "success");
        await refreshImages();
      } else if (response.status === "cancelled") {
        pushToast("任务已取消", `镜像 ${response.image} 已停止处理并清理本地产物。`, "success");
        await refreshImages();
      } else if (response.status === "failed") {
        pushToast("任务失败", response.error || "后端返回失败状态。", "error");
      }
    }

    renderTasks();
  } catch (error) {
    if (error.message.includes("was not found")) {
      removeTask(taskId);
      renderTasks();
      return;
    }

    if (notifyOnError) {
      pushToast("任务状态获取失败", error.message, "error");
    }
  }
}

function upsertTask(task) {
  const nextTasks = rootState.tasks.filter((item) => item.task_id !== task.task_id);
  nextTasks.unshift(task);
  rootState.tasks = nextTasks.slice(0, MAX_STORED_TASKS);
  persistTasks();
}

function removeTask(taskId) {
  rootState.tasks = rootState.tasks.filter((item) => item.task_id !== taskId);
  persistTasks();
}

function renderApiTarget() {
  elements.apiEndpoint.textContent = rootState.apiBaseUrl || window.location.origin;
}

function renderTasks() {
  const tasks = rootState.tasks.filter((task) => task.status !== "cancelled");
  const cancelledTasks = rootState.tasks.filter((task) => task.status === "cancelled");

  elements.summaryTotal.textContent = String(tasks.length);
  elements.summaryRunning.textContent = String(
    tasks.filter((task) => task.status === "pending" || task.status === "running").length,
  );
  elements.summarySuccess.textContent = String(
    tasks.filter((task) => task.status === "success").length,
  );
  elements.summaryFailed.textContent = String(
    tasks.filter((task) => task.status === "failed").length,
  );

  if (tasks.length === 0) {
    elements.taskList.innerHTML = `
      <div class="empty-state">
        <h3>还没有任务</h3>
        <p>输入镜像名后提交，最近任务会在这里持续显示。</p>
      </div>
    `;
  } else {
    elements.taskList.innerHTML = tasks.map(renderTaskCard).join("");
  }

  renderCancelledTasks(cancelledTasks);
  bindTaskActions();
}

function renderTaskCard(task) {
  const statusClass = `status-${task.status}`;
  const logs = Array.isArray(task.logs) && task.logs.length > 0
    ? escapeHtml(task.logs.join("\n"))
    : "暂无日志输出。";
  const filenameBlock = task.filename
    ? `<div class="task-row"><span class="task-meta">归档文件</span><strong>${escapeHtml(task.filename)}</strong></div>`
    : "";
  const errorBlock = task.error
    ? `<div class="task-error">${escapeHtml(task.error)}</div>`
    : "";
  const observedAt = task.observed_at
    ? formatDateTime(task.observed_at)
    : "刚刚";
  const actionBlock = task.status === "running"
    ? `
      <div class="task-actions">
        <button class="danger-button" type="button" data-cancel-task-id="${escapeHtml(task.task_id)}">
          取消当前任务
        </button>
      </div>
    `
    : "";

  return `
    <article class="task-card">
      <div class="task-head">
        <div>
          <h3 class="task-title">${escapeHtml(task.image)}</h3>
          <div class="task-meta">
            <span>Task ID: ${escapeHtml(task.task_id)}</span>
            <span>最近更新 ${escapeHtml(observedAt)}</span>
          </div>
        </div>
        <span class="status-badge ${statusClass}">${escapeHtml(task.status)}</span>
      </div>
      ${filenameBlock}
      ${errorBlock}
      ${actionBlock}
      <details class="log-frame" ${task.status === "running" ? "open" : ""}>
        <summary>查看日志</summary>
        <pre class="task-log">${logs}</pre>
      </details>
    </article>
  `;
}

function renderCancelledTasks(tasks) {
  if (tasks.length === 0) {
    elements.cancelledTasksPanel.hidden = true;
    elements.cancelledTaskList.innerHTML = "";
    return;
  }

  elements.cancelledTasksPanel.hidden = false;
  elements.cancelledTaskList.innerHTML = tasks.map(renderCancelledTaskCard).join("");
}

function renderCancelledTaskCard(task) {
  const logs = Array.isArray(task.logs) && task.logs.length > 0
    ? escapeHtml(task.logs.join("\n"))
    : "暂无日志输出。";
  const observedAt = task.observed_at
    ? formatDateTime(task.observed_at)
    : "刚刚";

  return `
    <article class="task-card">
      <div class="task-head">
        <div>
          <h3 class="task-title">${escapeHtml(task.image)}</h3>
          <div class="task-meta">
            <span>Task ID: ${escapeHtml(task.task_id)}</span>
            <span>最近更新 ${escapeHtml(observedAt)}</span>
          </div>
        </div>
        <span class="status-badge status-cancelled">cancelled</span>
      </div>
      <div class="task-actions">
        <button class="secondary-button" type="button" data-delete-task-id="${escapeHtml(task.task_id)}">
          删除记录
        </button>
      </div>
      <details class="log-frame">
        <summary>查看日志</summary>
        <pre class="task-log">${logs}</pre>
      </details>
    </article>
  `;
}

function renderImages() {
  const images = rootState.images;
  const totalBytes = images.reduce((sum, item) => sum + Number(item.size_bytes || 0), 0);

  elements.archiveCount.textContent = String(images.length);
  elements.archiveTotalSize.textContent = formatBytes(totalBytes);

  if (images.length === 0) {
    elements.imageList.innerHTML = `
      <div class="empty-state">
        <h3>还没有归档文件</h3>
        <p>任务成功后，镜像 tar 包会出现在这里，可直接下载或删除。</p>
      </div>
    `;
    return;
  }

  elements.imageList.innerHTML = images.map(renderImageCard).join("");
  bindImageActions();
}

function renderImageCard(image) {
  const filename = image.filename || "unknown.tar";
  const downloadUrl = `${rootState.apiBaseUrl}/images/${encodeURIComponent(filename)}/download`;
  const savedAt = image.saved_at ? formatDateTime(image.saved_at) : "未知时间";

  return `
    <article class="image-card">
      <div class="image-head">
        <div>
          <h3 class="image-title">${escapeHtml(filename)}</h3>
          <div class="image-meta">
            <span>${escapeHtml(formatBytes(Number(image.size_bytes || 0)))}</span>
            <span>${escapeHtml(savedAt)}</span>
          </div>
        </div>
      </div>
      <div class="image-actions">
        <a class="primary-button" href="${downloadUrl}">下载归档</a>
        <button class="danger-button" type="button" data-delete-filename="${escapeHtml(filename)}">删除文件</button>
      </div>
    </article>
  `;
}

function bindImageActions() {
  document.querySelectorAll("[data-delete-filename]").forEach((button) => {
    button.addEventListener("click", async () => {
      const filename = button.dataset.deleteFilename || "";
      if (!filename) {
        return;
      }

      const confirmed = window.confirm(`确认删除归档 ${filename} 吗？此操作不可恢复。`);
      if (!confirmed) {
        return;
      }

      button.disabled = true;
      try {
        await apiFetch(`/images/${encodeURIComponent(filename)}`, {
          method: "DELETE",
        });
        pushToast("归档已删除", `${filename} 已从服务器移除。`, "success");
        await refreshImages();
      } catch (error) {
        pushToast("删除失败", error.message, "error");
      } finally {
        button.disabled = false;
      }
    });
  });
}

function bindTaskActions() {
  document.querySelectorAll("[data-cancel-task-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      const taskId = button.dataset.cancelTaskId || "";
      const task = rootState.tasks.find((item) => item.task_id === taskId);
      if (!taskId || !task) {
        return;
      }

      const confirmed = window.confirm(
        `确认取消当前任务 ${task.image} 吗？系统会尝试终止 Docker 进程并删除本地镜像与未完成归档。`,
      );
      if (!confirmed) {
        return;
      }

      button.disabled = true;
      try {
        const response = await apiFetch(`/tasks/${encodeURIComponent(taskId)}/cancel`, {
          method: "POST",
        });
        upsertTask({
          ...response,
          observed_at: new Date().toISOString(),
        });
        pushToast("任务已取消", `镜像 ${response.image} 已停止处理。`, "success");
        await refreshImages();
        renderTasks();
      } catch (error) {
        pushToast("取消失败", error.message, "error");
      } finally {
        button.disabled = false;
      }
    });
  });

  document.querySelectorAll("[data-delete-task-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      const taskId = button.dataset.deleteTaskId || "";
      if (!taskId) {
        return;
      }

      const confirmed = window.confirm("确认删除这条已取消任务记录吗？");
      if (!confirmed) {
        return;
      }

      button.disabled = true;
      try {
        await apiFetch(`/tasks/${encodeURIComponent(taskId)}`, {
          method: "DELETE",
        });
        removeTask(taskId);
        renderTasks();
        pushToast("记录已删除", `取消任务 ${taskId} 已从面板中移除。`, "success");
      } catch (error) {
        pushToast("删除记录失败", error.message, "error");
      } finally {
        button.disabled = false;
      }
    });
  });
}

async function apiFetch(path, options = {}) {
  const url = `${rootState.apiBaseUrl}${path}`;
  const response = await window.fetch(url, options);
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    const detail = typeof payload === "string"
      ? payload
      : payload?.detail || JSON.stringify(payload);
    throw new Error(detail || `${response.status} ${response.statusText}`);
  }

  return payload;
}

function formatBytes(sizeBytes) {
  if (!Number.isFinite(sizeBytes) || sizeBytes < 0) {
    return "0 B";
  }

  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = sizeBytes;
  let unitIndex = 0;

  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }

  return `${size.toFixed(size >= 10 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

function formatDateTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "未知时间";
  }

  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

function pushToast(title, message, variant) {
  const toast = document.createElement("article");
  toast.className = `toast toast-${variant}`;
  toast.innerHTML = `
    <strong>${escapeHtml(title)}</strong>
    <p>${escapeHtml(message)}</p>
  `;
  elements.toastRegion.appendChild(toast);

  window.setTimeout(() => {
    toast.remove();
  }, 3600);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

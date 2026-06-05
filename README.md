# docker_image_mirror_tool

## Frontend

Static frontend files live in `frontend/`.

For local testing:

1. Start the backend API on `127.0.0.1:8000`.
2. Serve the frontend directory with a static file server, for example:

```bash
cd frontend
python -m http.server 4173
```

3. Open `http://127.0.0.1:4173`.

## Docker Packaging

This project can be containerized after decided which Docker daemon the backend talks to.

### Option 1: Isolated sidecar daemon (`docker-compose.dind.yml`)

Recommended when you do not want task cancellation or image cleanup to touch the host machine's Docker images.

```bash
docker compose -f docker-compose.dind.yml up -d --build
```

This starts:

- `api`: FastAPI backend with Docker CLI inside the container
- `web`: nginx serving the static frontend and proxying `/images` and `/tasks`
- `docker-daemon`: a dedicated `docker:dind` daemon used only by this app

The backend talks to `tcp://docker-daemon:2375`, so all `docker pull/save/image rm` operations stay inside the dedicated daemon instead of the host daemon.

### Option 2: Host Docker socket (`docker-compose.socket.yml`)

Use this only when you explicitly want the app to operate on the host Docker daemon.

```bash
docker compose -f docker-compose.socket.yml up -d --build
```

This mounts `/var/run/docker.sock` into the backend container. It is simpler, but it effectively gives the container host-level Docker control.

### Cancellation cleanup behavior

The backend now supports:

- `CLEANUP_LOCAL_IMAGE_ON_CANCEL=true`: preserve the old behavior and run `docker image rm -f` after cancellation
- `CLEANUP_LOCAL_IMAGE_ON_CANCEL=false`: stop the running task and delete unfinished tar output, but keep the local Docker image in the connected daemon

Both compose examples set `CLEANUP_LOCAL_IMAGE_ON_CANCEL=false` by default.

## Docker 打包说明

在打包这个项目为 Docker 镜像运行前，需要决定后端最终连接的是哪个 Docker daemon。

### 方案一：独立 sidecar daemon（`docker-compose.dind.yml`）

如果你不希望取消任务或镜像清理影响宿主机上的 Docker 镜像，推荐使用这个方案。

```bash
docker compose -f docker-compose.dind.yml up -d --build
```

这个编排会启动：

- `api`：FastAPI 后端，容器内带 Docker CLI
- `web`：nginx，负责提供前端静态文件并代理 `/images` 和 `/tasks`
- `docker-daemon`：独立的 `docker:dind`，只给这个项目使用

其中 `web` 暴露的是宿主机 `80` 端口，对应 compose 里的 `80:80`，启动后可直接通过 `http://服务器IP/` 访问。

后端通过 `tcp://docker-daemon:2375` 连接这个独立 daemon，所以 `docker pull`、`docker save`、`docker image rm` 这些操作都会发生在独立 daemon 内，而不是宿主机 daemon 上。

### 方案二：挂宿主机 Docker socket（`docker-compose.socket.yml`）

只有在你明确希望这个应用直接操作宿主机 Docker daemon 时，才建议使用这个方案。

```bash
docker compose -f docker-compose.socket.yml up -d --build
```

这个方案会把 `/var/run/docker.sock` 挂进后端容器。优点是简单，缺点是容器实际上获得了宿主机 Docker 的高权限访问能力。

### 取消任务时的清理行为

后端现在支持通过环境变量控制取消任务后的本地镜像清理：

- `CLEANUP_LOCAL_IMAGE_ON_CANCEL=true`：保留原行为，任务取消后执行 `docker image rm -f`
- `CLEANUP_LOCAL_IMAGE_ON_CANCEL=false`：只停止任务并删除未完成的 tar 文件，不删除已拉到当前 daemon 里的本地镜像

两份 compose 示例默认都设置为 `CLEANUP_LOCAL_IMAGE_ON_CANCEL=false`。

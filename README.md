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

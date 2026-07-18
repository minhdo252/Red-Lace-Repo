# DEPLOY — Hướng dẫn deploy / update từ bất kỳ máy nào

> App đã LIVE. File này để **deploy bản cập nhật mới** (hoặc dựng lại từ đầu) từ một máy khác.
> Không chứa secret — giá trị key/token nằm ở `backend/.env`, `frontend/.env.local` (đều gitignored)
> và đã được set sẵn trên Railway + Vercel.

## 🌐 App đang chạy ở đâu
| Thành phần | URL / định danh |
|---|---|
| **Frontend (Vercel)** | https://nonai-three.vercel.app |
| **Backend (Railway)** | https://nonai-backend-production.up.railway.app  (`/health` → `{"status":"ok"}`) |
| GitHub repo | https://github.com/minhdo252/Red-Lace-Repo  (private, nhánh `main`) |

**Railway** — project `nonai-backend` (id `4f35d7e2-6ed1-44e4-b4cb-0eb8e9749ff9`), env `production`, 3 service:
`nonai-backend` (FastAPI, id `f97096f6-f0c7-46b5-bce6-0898de0dd6e7`) · `Postgres` · `qdrant`.

**Vercel** — project `nonai` · projectId `prj_nHImfGpuP8LHiiAVmvlMXKS9mH9I` · org `team_cdmOkWuR97A5rxthTxrn8VaE` · scope `mdsat-s-projects`.

---

## ⚡ TL;DR — update nhanh (env đã có sẵn trên cloud, KHÔNG cần nhập lại key)

```bash
# 1. Lấy code mới nhất
git clone https://github.com/minhdo252/Red-Lace-Repo.git
cd Red-Lace-Repo

# 2. Backend (Railway) — nếu có sửa gì trong backend/
npm i -g @railway/cli
railway login                       # đăng nhập browser (1 lần)
railway link                        # chọn workspace → project "nonai-backend"
cd backend && railway up --service nonai-backend

# 3. Frontend (Vercel) — nếu có sửa gì trong frontend/
npm i -g vercel
cd ../frontend && vercel link       # chọn scope mdsat-s-projects → project "nonai"
vercel --prod --yes --scope mdsat-s-projects
```

> **Quan trọng:** các API key + `BACKEND_URL` + `SERPAPI_KEY` đã lưu **trên Railway/Vercel** rồi.
> Deploy update **không cần** nhập lại. Chỉ khi *dựng mới từ đầu* mới cần (xem mục cuối).

---

## 1. Yêu cầu công cụ (cài 1 lần trên máy mới)
| Công cụ | Cài | Ghi chú |
|---|---|---|
| Git | https://git-scm.com | trên Windows nếu `git` không có trong PATH: thêm `C:\Program Files\Git\cmd` |
| Node.js ≥ 20 | https://nodejs.org | kèm `npm` / `npx` |
| Railway CLI | `npm i -g @railway/cli` | deploy backend |
| Vercel CLI | `npm i -g vercel` | deploy frontend |
| GitHub CLI (tùy chọn) | https://cli.github.com | `gh auth login` để push repo private |

---

## 2. Lấy code
```bash
git clone https://github.com/minhdo252/Red-Lace-Repo.git
cd Red-Lace-Repo
```
Repo là **private** → cần đăng nhập GitHub (qua `gh auth login`, hoặc HTTPS + Personal Access Token).

---

## 3. Deploy UPDATE — Backend (Railway)

```bash
railway login                                   # 1 lần / máy (mở browser)
railway link                                    # chọn: workspace → project "nonai-backend" → env "production"
cd backend
railway up --service nonai-backend              # build + deploy (Dockerfile), zero-downtime
```
- Railway tự build bằng `backend/Dockerfile`, chạy `start.sh` (seed nền + `uvicorn` trên `$PORT`).
- Muốn không đợi log: thêm `--detach`. Theo dõi: `railway logs --service nonai-backend`.
- Restart không build lại: `railway redeploy --service nonai-backend`.
- Đổi 1 biến env: `railway variables --service nonai-backend --set 'TÊN=giá_trị'` rồi redeploy.

## 4. Deploy UPDATE — Frontend (Vercel)

```bash
cd frontend
vercel link                                     # nếu chưa: chọn scope mdsat-s-projects → project "nonai"
vercel --prod --yes --scope mdsat-s-projects    # build trên cloud → alias nonai-three.vercel.app
```
- Không cần `npm install` trước — Vercel tự cài sạch khi build.
- Xác thực Vercel: hoặc `vercel login`, hoặc set biến `VERCEL_TOKEN` (`vercel --prod --token <...>`).

---

## 5. Kiểm tra sau khi deploy (verify)
```bash
# Backend sống
curl https://nonai-backend-production.up.railway.app/health          # -> {"status":"ok"}

# Frontend nối backend thật (source phải là "backend")
curl -X POST https://nonai-three.vercel.app/api/session \
  -H "Content-Type: application/json" \
  -d '{"native_language":"en","nationality":"US"}'                    # -> {"source":"backend","session_id":"..."}

# Map dùng Google thật
curl "https://nonai-three.vercel.app/api/nearby?q=pho&lat=21.0333&lon=105.85"   # -> source:"serpapi"
```
Trên UI: onboarding → chat ra trả lời AI thật; price-check đọc hoá đơn; SOS ra hotline + đúng đại sứ quán; map ra địa điểm thật.

---

## 6. Push code lên GitHub (từ máy khác)
```bash
git add -A
git commit -m "..."
git push origin main            # nếu treo ở credential helper, dùng token URL:
# git -c credential.helper= push "https://x-access-token:$(gh auth token)@github.com/minhdo252/Red-Lace-Repo.git" HEAD:main
```

---

## 7. Env vars — dùng đúng tên (giá trị KHÔNG để trong file này)

**Backend (Railway service `nonai-backend`)** — đã set sẵn; chỉ cần set lại khi *dựng mới*:
```
AI_MODE=live
AI_BASE_URL=https://mkp-api.fptcloud.com
AI_CHAT_API_KEY=…   GLM_API_KEY=…            AI_CHAT_MODEL=GLM-5.2
AI_VISION_API_KEY=… QWEN_VL_API_KEY=…        AI_VISION_MODEL=Qwen2.5-VL-7B-Instruct
AI_EMBED_API_KEY=…  VN_EMBEDDING_API_KEY=…   AI_EMBED_MODEL=Vietnamese_Embedding   EMBEDDING_DIM=1024
AI_STT_API_KEY=…    WHISPER_V3_API_KEY=…     STT_MODEL=FPT.AI-whisper-large-v3-turbo
GEMINI_API_KEY=…    TAVILY_API_KEY=…
MOCK_GOOGLE_PLACES=true
POSTGRES_DSN=${{Postgres.DATABASE_URL}}      QDRANT_URL=http://qdrant.railway.internal:6333
PORT=8000
```
**Frontend (Vercel `nonai`)**: `BACKEND_URL` (Production + Preview) = URL backend Railway; `SERPAPI_KEY` (Production).

👉 **Giá trị thật** nằm ở `backend/.env` và `frontend/.env.local` (gitignored). Muốn chép sang máy mới:
copy **2 file này** qua kênh an toàn (USB / trình quản lý mật khẩu), **đừng** đưa lên git/chat.

---

## 8. Dựng lại TỪ ĐẦU (nếu tạo project Railway mới)
Chỉ cần khi làm project Railway hoàn toàn mới. Các bước (đã tự động hoá được bằng CLI):
```bash
railway login
railway init --name nonai-backend                       # tạo project
railway add --database postgres                          # thêm Postgres
railway add --image qdrant/qdrant:latest --service qdrant
railway add --service nonai-backend                      # service cho FastAPI
# set toàn bộ env ở mục 7 (giá trị lấy từ backend/.env):
railway variables --service nonai-backend --set 'AI_MODE=live' --set 'GLM_API_KEY=…' … --skip-deploys
cd backend && railway up --service nonai-backend         # deploy
railway domain --service nonai-backend --port 8000       # tạo URL public
# rồi set BACKEND_URL trên Vercel = URL vừa tạo, và deploy frontend (mục 4)
```
Schema DB **tự tạo** khi backend khởi động (`app/db/postgres.py::ensure_runtime_schema`), seed chạy nền qua `start.sh` — **không cần `psql`**.

---

## 9. Gotchas (lỗi đã gặp & cách tránh)
- **Port:** app bind `${PORT:-8000}`; domain Railway trỏ cổng **8000** và biến `PORT=8000` đã pin. Nếu 502 → kiểm tra log `Uvicorn running on 0.0.0.0:<port>` khớp cổng domain.
- **`start.sh` phải là LF** (không CRLF), nếu không bash trong container lỗi → giữ `.gitattributes`/editor ở LF.
- **Managed Postgres không chạy `db/init.sql`** → schema do app tự bootstrap (đã xử lý trong code).
- **Vercel:** `.vercel` bị gitignore → máy mới phải `vercel link` lại (chọn đúng project `nonai`).
- **Đường dẫn có dấu tiếng Việt** làm hỏng vài tool → clone repo vào đường dẫn ASCII (vd `C:\...\RedLace\`).
- **Windows:** dùng **PowerShell** (Bash git ở máy dev bị lỗi một phần); `git` có thể không sẵn PATH.
- **Seed nền:** lần deploy đầu seed 30+20 mẫu scam vào Qdrant và 592 dòng giá vào Postgres; các lần sau tự bỏ qua (idempotent) nên khởi động nhanh.

---

## 10. Bảo mật
- Không commit `backend/.env`, `frontend/.env.local`, hay bất kỳ token nào.
- Token deploy (Vercel/Railway) và API key cho quyền quản lý tài khoản → **rotate** sau hackathon nếu đã lộ.
- Railway đăng nhập bằng session (`railway logout` để thu hồi); Vercel token quản lý tại https://vercel.com/account/settings/tokens.

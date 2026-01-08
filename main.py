import uvicorn
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
import aiosqlite
import os
import shutil
import uuid

app = FastAPI()

# 配置
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-here")  # 生产环境请使用环境变量覆盖
DATABASE = "social.db"
UPLOAD_DIR = "static/uploads"
PRIVATE_UPLOAD_DIR = "private_uploads"
ADMIN_PASSWORD = "admin"  # 简单演示用管理员密码

# 确保上传目录存在
os.makedirs(f"{UPLOAD_DIR}/avatars", exist_ok=True)
os.makedirs(f"{PRIVATE_UPLOAD_DIR}/id_cards", exist_ok=True)

# 挂载静态文件
app.mount("/static", StaticFiles(directory="static"), name="static")

# 添加 Session 中间件用于保持登录状态
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

# 模板引擎
templates = Jinja2Templates(directory="templates")

# 数据库初始化
async def init_db():
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                gender TEXT,
                age_range TEXT,
                country TEXT,
                avatar_path TEXT,
                id_card_path TEXT,
                is_verified BOOLEAN DEFAULT 0,
                ip_address TEXT,
                name TEXT,
                dob TEXT,
                state TEXT,
                city TEXT,
                hair_color TEXT,
                eye_color TEXT,
                height TEXT,
                weight TEXT,
                marital_status TEXT,
                smoking TEXT,
                match_gender TEXT,
                match_age_min INTEGER,
                match_age_max INTEGER,
                asset_proof_path TEXT,
                is_ai BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_photos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                photo_path TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER NOT NULL,
                receiver_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                read_at TIMESTAMP NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS profile_views (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                viewer_id INTEGER NOT NULL,
                viewed_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS likes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                liker_id INTEGER NOT NULL,
                liked_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(liker_id, liked_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recipient_id INTEGER NOT NULL,
                actor_id INTEGER NOT NULL,
                type TEXT NOT NULL, -- 'view' | 'like'
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                read_at TIMESTAMP NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS favorites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                favoriter_id INTEGER NOT NULL,
                favorite_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(favoriter_id, favorite_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS blocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                blocker_id INTEGER NOT NULL,
                blocked_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(blocker_id, blocked_id)
            )
        """)
        
        # 尝试添加新字段（如果表已存在）
        new_columns = [
            "avatar_path TEXT", "id_card_path TEXT", "is_verified BOOLEAN DEFAULT 0",
            "ip_address TEXT", "name TEXT", "dob TEXT", "state TEXT", "city TEXT",
            "hair_color TEXT", "eye_color TEXT", "height TEXT", "weight TEXT",
            "marital_status TEXT", "smoking TEXT", "match_gender TEXT",
            "match_age_min INTEGER", "match_age_max INTEGER",
            "asset_proof_path TEXT", "is_ai BOOLEAN DEFAULT 0", "last_active_at TIMESTAMP"
        ]
        
        for col in new_columns:
            try:
                await db.execute(f"ALTER TABLE users ADD COLUMN {col}")
            except:
                pass
            
        await db.commit()

# 获取真实IP辅助函数
def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0]
    return request.client.host

@app.on_event("startup")
async def startup():
    await init_db()
    async with aiosqlite.connect(DATABASE) as db:
        async with db.execute("SELECT id FROM users WHERE is_ai = 1 LIMIT 1") as cursor:
            bot = await cursor.fetchone()
        if not bot:
            await db.execute(
                "INSERT INTO users (phone, password, gender, age_range, country, name, is_verified, is_ai) VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
                ("BOT", "bot", None, None, None, "系统助手", 1)
            )
            await db.commit()

# 静态页面路由
@app.get("/terms", response_class=HTMLResponse)
async def terms(request: Request):
    return templates.TemplateResponse("terms.html", {"request": request})

@app.get("/privacy", response_class=HTMLResponse)
async def privacy(request: Request):
    return templates.TemplateResponse("privacy.html", {"request": request})

@app.get("/safety", response_class=HTMLResponse)
async def safety(request: Request):
    return templates.TemplateResponse("safety.html", {"request": request})

@app.get("/about", response_class=HTMLResponse)
async def about(request: Request):
    return templates.TemplateResponse("about.html", {"request": request})

# 路由
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    # 如果已登录，跳转到大厅
    if "user_id" in request.session:
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/register")
async def register(
    request: Request,
    phone: str = Form(...),
    password: str = Form(...),
    gender: str = Form(...),
    age_range: str = Form(...),
    country: str = Form(...),
    agreement: bool = Form(False)
):
    if not agreement:
        return templates.TemplateResponse("index.html", {
            "request": request,
            "error": "必须同意《用户协议》与《隐私政策》才能注册。",
            "active_tab": "register"
        })

    try:
        ip = get_client_ip(request)
        async with aiosqlite.connect(DATABASE) as db:
            # 检查手机号是否已存在
            async with db.execute("SELECT id FROM users WHERE phone = ?", (phone,)) as cursor:
                if await cursor.fetchone():
                    return templates.TemplateResponse("index.html", {
                        "request": request,
                        "error": "该手机号已被注册。",
                        "active_tab": "register"
                    })
            
            # 插入新用户
            await db.execute("""
                INSERT INTO users (phone, password, gender, age_range, country, ip_address)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (phone, password, gender, age_range, country, ip))
            await db.commit()
            
            # 自动登录
            async with db.execute("SELECT id FROM users WHERE phone = ?", (phone,)) as cursor:
                user = await cursor.fetchone()
                request.session["user_id"] = user[0]

            async with db.execute("SELECT id FROM users WHERE is_ai = 1 LIMIT 1") as cursor:
                bot = await cursor.fetchone()
            if bot:
                welcome = "欢迎加入 GlobalAsianElite！我是系统助手（AI）。如需帮助，请回复：帮助"
                await db.execute("INSERT INTO messages (sender_id, receiver_id, content) VALUES (?, ?, ?)", (bot[0], user[0], welcome))
                await db.commit()
                
        # 注册成功后跳转到认证页面
        return RedirectResponse(url="/verify", status_code=303)
        
    except Exception as e:
        return templates.TemplateResponse("index.html", {
            "request": request,
            "error": f"注册失败: {str(e)}",
            "active_tab": "register"
        })

@app.get("/login")
async def login_get(request: Request):
    return RedirectResponse(url="/")

@app.post("/login")
async def login(
    request: Request,
    phone: str = Form(...),
    password: str = Form(...)
):
    ip = get_client_ip(request)
    async with aiosqlite.connect(DATABASE) as db:
        async with db.execute("SELECT id, password FROM users WHERE phone = ?", (phone,)) as cursor:
            user = await cursor.fetchone()
            if not user or user[1] != password:
                return templates.TemplateResponse("index.html", {
                    "request": request,
                    "error": "账号或密码错误。",
                    "active_tab": "login"
                })
            
            # 更新登录 IP
            await db.execute("UPDATE users SET ip_address = ? WHERE id = ?", (ip, user[0]))
            await db.commit()

            # 登录成功
            request.session["user_id"] = user[0]
            return RedirectResponse(url="/dashboard", status_code=303)

@app.get("/profile/edit", response_class=HTMLResponse)
async def profile_edit_page(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=303)
        
    async with aiosqlite.connect(DATABASE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE id = ?", (user_id,)) as cursor:
            user = await cursor.fetchone()
            
    return templates.TemplateResponse("profile_edit.html", {"request": request, "user": user})

@app.post("/profile/update")
async def profile_update(
    request: Request,
    name: str = Form(None),
    dob_year: str = Form(None),
    dob_month: str = Form(None),
    dob_day: str = Form(None),
    state: str = Form(None),
    city: str = Form(None),
    hair_color: str = Form(None),
    eye_color: str = Form(None),
    height: str = Form(None),
    weight: str = Form(None),
    match_gender: str = Form(None),
    match_age_min: int = Form(None),
    match_age_max: int = Form(None),
):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=303)
        
    dob = f"{dob_year}-{dob_month}-{dob_day}" if dob_year and dob_month and dob_day else None
    
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("""
            UPDATE users SET 
            name=?, dob=?, state=?, city=?, hair_color=?, eye_color=?, height=?, weight=?,
            match_gender=?, match_age_min=?, match_age_max=?
            WHERE id=?
        """, (name, dob, state, city, hair_color, eye_color, height, weight,
               match_gender, match_age_min, match_age_max, user_id))
        await db.commit()
        
    return RedirectResponse(url="/profile/photos", status_code=303)

@app.get("/profile/photos", response_class=HTMLResponse)
async def profile_photos_page(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=303)
    
    async with aiosqlite.connect(DATABASE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE id = ?", (user_id,)) as cursor:
            user = await cursor.fetchone()
        async with db.execute("SELECT photo_path FROM user_photos WHERE user_id = ? ORDER BY id DESC LIMIT 4", (user_id,)) as cursor:
            photos = await cursor.fetchall()
            
    return templates.TemplateResponse("profile_photos.html", {"request": request, "user": user, "photos": photos})

# 验证页面 (原 verification.html)
@app.get("/verification", response_class=HTMLResponse)
async def verify_page(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/")
    return templates.TemplateResponse("verification.html", {"request": request})

@app.post("/verify")
async def verify(
    request: Request,
    avatar: UploadFile = File(None),
    id_card: UploadFile = File(None),
    asset_proof: UploadFile = File(None)
):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=303)

    avatar_path = None
    id_card_path = None
    asset_proof_path = None

    # 处理头像上传 (公开)
    if avatar and avatar.filename:
        ext = os.path.splitext(avatar.filename)[1]
        filename = f"{user_id}_{uuid.uuid4()}{ext}"
        filepath = f"{UPLOAD_DIR}/{filename}"
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(avatar.file, buffer)
        avatar_path = f"/static/uploads/{filename}"

    # 处理证件上传 (私密)
    if id_card and id_card.filename:
        ext = os.path.splitext(id_card.filename)[1]
        filename = f"{user_id}_{uuid.uuid4()}{ext}"
        filepath = f"{PRIVATE_UPLOAD_DIR}/id_cards/{filename}"
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(id_card.file, buffer)
        id_card_path = filepath
        
    # 处理资产证明上传 (私密)
    if asset_proof and asset_proof.filename:
        ext = os.path.splitext(asset_proof.filename)[1]
        filename = f"{user_id}_{uuid.uuid4()}{ext}"
        # 存放在 id_cards 同级或新建文件夹，这里复用 id_cards 文件夹或新建 asset_proofs
        asset_dir = f"{PRIVATE_UPLOAD_DIR}/assets"
        os.makedirs(asset_dir, exist_ok=True)
        filepath = f"{asset_dir}/{filename}"
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(asset_proof.file, buffer)
        asset_proof_path = filepath

    async with aiosqlite.connect(DATABASE) as db:
        if avatar_path:
            await db.execute("UPDATE users SET avatar_path = ? WHERE id = ?", (avatar_path, user_id))
        if id_card_path:
            await db.execute("UPDATE users SET id_card_path = ? WHERE id = ?", (id_card_path, user_id))
        if asset_proof_path:
            await db.execute("UPDATE users SET asset_proof_path = ? WHERE id = ?", (asset_proof_path, user_id))
        await db.commit()

    if avatar_path and not id_card_path and not asset_proof_path:
        return RedirectResponse(url="/profile/photos?uploaded=1", status_code=303)
    return RedirectResponse(url="/dashboard", status_code=303)

@app.post("/photo/upload")
async def photo_upload(request: Request, photo: UploadFile = File(...)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=303)

    if not photo or not photo.filename:
        return RedirectResponse(url="/profile/photos", status_code=303)

    ext = os.path.splitext(photo.filename)[1]
    filename = f"{user_id}_{uuid.uuid4()}{ext}"
    filepath = f"{UPLOAD_DIR}/{filename}"
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(photo.file, buffer)
    photo_path = f"/static/uploads/{filename}"

    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("INSERT INTO user_photos (user_id, photo_path) VALUES (?, ?)", (user_id, photo_path))
        await db.commit()

    return RedirectResponse(url="/profile/photos?uploaded=1", status_code=303)

@app.get("/messages", response_class=HTMLResponse)
async def messages_page(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=303)
        
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("UPDATE users SET last_active_at = CURRENT_TIMESTAMP WHERE id = ?", (user_id,))
        await db.commit()
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE id = ?", (user_id,)) as cursor:
            user = await cursor.fetchone()
        async with db.execute("SELECT id, name, country, avatar_path, is_verified, is_ai FROM users WHERE id != ? ORDER BY id DESC LIMIT 50", (user_id,)) as cursor:
            members = await cursor.fetchall()
        last_msgs = {}
        for m in members:
            async with db.execute(
                """
                SELECT content, created_at, sender_id FROM messages
                WHERE (sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?)
                ORDER BY id DESC LIMIT 1
                """,
                (user_id, m["id"], m["id"], user_id)
            ) as cur:
                row = await cur.fetchone()
                last_msgs[m["id"]] = row
            
    return templates.TemplateResponse("messages.html", {"request": request, "user": user, "members": members, "last_msgs": last_msgs})

@app.get("/member/{member_id}", response_class=HTMLResponse)
async def member_page(request: Request, member_id: int):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=303)
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("UPDATE users SET last_active_at = CURRENT_TIMESTAMP WHERE id = ?", (user_id,))
        await db.commit()
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT id, name, gender, age_range, country, city, avatar_path, is_verified, is_ai FROM users WHERE id = ?", (member_id,)) as cursor:
            member = await cursor.fetchone()
        if not member:
            raise HTTPException(status_code=404, detail="用户不存在")
        if user_id != member_id:
            await db.execute("INSERT INTO profile_views (viewer_id, viewed_id) VALUES (?, ?)", (user_id, member_id))
            await db.execute("INSERT INTO notifications (recipient_id, actor_id, type) VALUES (?, ?, 'view')", (member_id, user_id))
            await db.commit()
    return templates.TemplateResponse("member.html", {"request": request, "member": member})

@app.get("/profile/showProfile/ID/{member_id}")
async def legacy_profile_redirect(request: Request, member_id: int, searchposition: int | None = None, searchtotal: int | None = None):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=303)
    return RedirectResponse(url=f"/member/{member_id}", status_code=303)

@app.get("/chat/{peer_id}", response_class=HTMLResponse)
async def chat_page(request: Request, peer_id: int):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=303)
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("UPDATE users SET last_active_at = CURRENT_TIMESTAMP WHERE id = ?", (user_id,))
        await db.commit()
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT id, name, avatar_path, country, is_verified FROM users WHERE id = ?", (peer_id,)) as cursor:
            peer = await cursor.fetchone()
        if not peer:
            raise HTTPException(status_code=404, detail="用户不存在")
        async with db.execute(
            """
            SELECT sender_id, receiver_id, content, created_at FROM messages
            WHERE (sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?)
            ORDER BY id ASC
            """,
            (user_id, peer_id, peer_id, user_id)
        ) as cursor:
            msgs = await cursor.fetchall()
        await db.execute("UPDATE messages SET read_at = CURRENT_TIMESTAMP WHERE receiver_id = ? AND sender_id = ? AND read_at IS NULL", (user_id, peer_id))
        await db.commit()
    return templates.TemplateResponse("chat.html", {"request": request, "peer": peer, "msgs": msgs})

@app.post("/chat/{peer_id}/send")
async def chat_send(request: Request, peer_id: int, content: str = Form(...)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=303)
    if not content.strip():
        return RedirectResponse(url=f"/chat/{peer_id}", status_code=303)
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("INSERT INTO messages (sender_id, receiver_id, content) VALUES (?, ?, ?)", (user_id, peer_id, content.strip()))
        await db.commit()
    return RedirectResponse(url=f"/chat/{peer_id}", status_code=303)

@app.get("/chat_box/{peer_id}")
async def chat_box(request: Request, peer_id: int):
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    async with aiosqlite.connect(DATABASE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT id, name, age_range, country, city, avatar_path, is_verified FROM users WHERE id = ?", (peer_id,)) as cursor:
            peer = await cursor.fetchone()
        if not peer:
            raise HTTPException(status_code=404, detail="用户不存在")
        async with db.execute(
            """
            SELECT sender_id, receiver_id, content, created_at FROM messages
            WHERE (sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?)
            ORDER BY id ASC
            """,
            (user_id, peer_id, peer_id, user_id)
        ) as cursor:
            msgs = await cursor.fetchall()
        await db.execute("UPDATE messages SET read_at = CURRENT_TIMESTAMP WHERE receiver_id = ? AND sender_id = ? AND read_at IS NULL", (user_id, peer_id))
        await db.commit()
    return {
        "peer": dict(peer),
        "msgs": [
            {"sender_id": m[0], "receiver_id": m[1], "content": m[2], "created_at": m[3]} for m in msgs
        ]
    }

@app.post("/chat_box/{peer_id}/send")
async def chat_box_send(request: Request, peer_id: int, content: str = Form(...)):
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    if not content.strip():
        return {"ok": False}
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("INSERT INTO messages (sender_id, receiver_id, content) VALUES (?, ?, ?)", (user_id, peer_id, content.strip()))
        await db.commit()
    return {"ok": True}

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/")
    
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("UPDATE users SET last_active_at = CURRENT_TIMESTAMP WHERE id = ?", (user_id,))
        await db.commit()
        # 获取当前用户信息
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE id = ?", (user_id,)) as cursor:
            current_user = await cursor.fetchone()
        f = request.query_params.get("filter")
        s = request.query_params.get("sort")
        country_filter = request.query_params.get("country")
        base = "FROM users u WHERE u.id != ? AND u.id NOT IN (SELECT blocked_id FROM blocks WHERE blocker_id = ?)"
        params = [user_id, user_id]
        if current_user and current_user["match_gender"] in ("male","female") and not f:
            base += " AND u.gender = ?"
            params.append(current_user["match_gender"])
        if f == "mutual":
            base += " AND EXISTS (SELECT 1 FROM likes l1 WHERE l1.liker_id = ? AND l1.liked_id = u.id) AND EXISTS (SELECT 1 FROM likes l2 WHERE l2.liker_id = u.id AND l2.liked_id = ?)"
            params += [user_id, user_id]
        elif f == "liked_me":
            base += " AND EXISTS (SELECT 1 FROM likes l WHERE l.liker_id = u.id AND l.liked_id = ?)"
            params += [user_id]
        elif f == "i_liked":
            base += " AND EXISTS (SELECT 1 FROM likes l WHERE l.liker_id = ? AND l.liked_id = u.id)"
            params += [user_id]
        elif f == "online":
            base += " AND u.last_active_at IS NOT NULL AND u.last_active_at >= datetime('now','-5 minutes')"
        elif f == "favorites":
            base += " AND EXISTS (SELECT 1 FROM favorites f WHERE f.favoriter_id = ? AND f.favorite_id = u.id)"
            params += [user_id]
        elif f == "my_region" and current_user and current_user["country"]:
            base += " AND u.country = ?"
            params += [current_user["country"]]
        if country_filter and country_filter != "popular":
            base += " AND u.country = ?"
            params += [country_filter]
        order = "u.id DESC"
        if s == "active":
            order = "u.last_active_at DESC"
        elif s == "verified":
            order = "u.is_verified DESC, u.id DESC"
        elif s == "photos":
            order = "(SELECT COUNT(1) FROM user_photos p WHERE p.user_id = u.id) DESC, u.id DESC"
        sql = f"SELECT u.id, u.name, u.gender, u.age_range, u.country, u.avatar_path, u.is_verified {base} ORDER BY {order} LIMIT 20"
        async with db.execute(sql, tuple(params)) as cursor:
            members = await cursor.fetchall()

        async with db.execute(
            """
            SELECT n.id, n.type, n.created_at, u.id as actor_id, u.name as actor_name, u.avatar_path as actor_avatar
            FROM notifications n
            JOIN users u ON u.id = n.actor_id
            WHERE n.recipient_id = ? AND n.read_at IS NULL
            ORDER BY n.id DESC
            LIMIT 10
            """,
            (user_id,)
        ) as cursor:
            notifications = await cursor.fetchall()

        async with db.execute("SELECT COUNT(*) FROM likes WHERE liked_id = ?", (user_id,)) as c:
            likes_count = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM favorites WHERE favoriter_id = ?", (user_id,)) as c:
            fav_count = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM profile_views WHERE viewed_id = ?", (user_id,)) as c:
            views_count = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM blocks WHERE blocker_id = ?", (user_id,)) as c:
            blocks_count = (await c.fetchone())[0]
        activity_counts = {
            "likes": likes_count,
            "favorites": fav_count,
            "views": views_count,
            "blocks": blocks_count
        }
        
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": current_user,
        "members": members,
        "notifications": notifications,
        "activity_counts": activity_counts,
        "filter": f or "",
        "sort": s or "",
        "country_filter": country_filter or ""
    })

@app.get("/activity", response_class=HTMLResponse)
async def activity_page(request: Request, type: str | None = None):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=303)
    async with aiosqlite.connect(DATABASE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT COUNT(*) FROM likes WHERE liked_id = ?", (user_id,)) as c:
            likes_count = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM favorites WHERE favoriter_id = ?", (user_id,)) as c:
            fav_count = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM profile_views WHERE viewed_id = ?", (user_id,)) as c:
            views_count = (await c.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM blocks WHERE blocker_id = ?", (user_id,)) as c:
            blocks_count = (await c.fetchone())[0]
        activity_counts = {
            "likes": likes_count,
            "favorites": fav_count,
            "views": views_count,
            "blocks": blocks_count
        }

        items = []
        if type == "likes":
            async with db.execute("""
                SELECT u.id, u.name, u.avatar_path, u.country, u.is_verified
                FROM likes l JOIN users u ON u.id = l.liker_id
                WHERE l.liked_id = ? ORDER BY l.id DESC LIMIT 100
            """, (user_id,)) as cursor:
                items = await cursor.fetchall()
        elif type == "favorites":
            async with db.execute("""
                SELECT u.id, u.name, u.avatar_path, u.country, u.is_verified
                FROM favorites f JOIN users u ON u.id = f.favorite_id
                WHERE f.favoriter_id = ? ORDER BY f.id DESC LIMIT 100
            """, (user_id,)) as cursor:
                items = await cursor.fetchall()
        elif type == "views":
            async with db.execute("""
                SELECT u.id, u.name, u.avatar_path, u.country, u.is_verified
                FROM profile_views v JOIN users u ON u.id = v.viewer_id
                WHERE v.viewed_id = ? ORDER BY v.id DESC LIMIT 100
            """, (user_id,)) as cursor:
                items = await cursor.fetchall()
        elif type == "blocks":
            async with db.execute("""
                SELECT u.id, u.name, u.avatar_path, u.country, u.is_verified
                FROM blocks b JOIN users u ON u.id = b.blocked_id
                WHERE b.blocker_id = ? ORDER BY b.id DESC LIMIT 100
            """, (user_id,)) as cursor:
                items = await cursor.fetchall()
        
    return templates.TemplateResponse("activity.html", {
        "request": request,
        "counts": activity_counts,
        "items": items,
        "type": type or "likes"
    })

@app.post("/favorite/{member_id}")
async def add_favorite(request: Request, member_id: int):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=303)
    async with aiosqlite.connect(DATABASE) as db:
        try:
            await db.execute("INSERT INTO favorites (favoriter_id, favorite_id) VALUES (?, ?)", (user_id, member_id))
        except Exception:
            pass
        await db.commit()
    return RedirectResponse(url=f"/member/{member_id}", status_code=303)

@app.post("/favorite/{member_id}/remove")
async def remove_favorite(request: Request, member_id: int):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=303)
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("DELETE FROM favorites WHERE favoriter_id = ? AND favorite_id = ?", (user_id, member_id))
        await db.commit()
    return RedirectResponse(url=f"/member/{member_id}", status_code=303)

@app.post("/block/{member_id}")
async def add_block(request: Request, member_id: int):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=303)
    async with aiosqlite.connect(DATABASE) as db:
        try:
            await db.execute("INSERT INTO blocks (blocker_id, blocked_id) VALUES (?, ?)", (user_id, member_id))
        except Exception:
            pass
        await db.commit()
    return RedirectResponse(url=f"/member/{member_id}", status_code=303)

@app.post("/block/{member_id}/remove")
async def remove_block(request: Request, member_id: int):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=303)
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("DELETE FROM blocks WHERE blocker_id = ? AND blocked_id = ?", (user_id, member_id))
        await db.commit()
    return RedirectResponse(url=f"/member/{member_id}", status_code=303)

@app.post("/like/{member_id}")
async def like_member(request: Request, member_id: int):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=303)
    if user_id == member_id:
        return RedirectResponse(url=f"/member/{member_id}", status_code=303)
    async with aiosqlite.connect(DATABASE) as db:
        try:
            await db.execute("INSERT INTO likes (liker_id, liked_id) VALUES (?, ?)", (user_id, member_id))
        except Exception:
            pass
        await db.execute("INSERT INTO notifications (recipient_id, actor_id, type) VALUES (?, ?, 'like')", (member_id, user_id))
        await db.commit()
    return RedirectResponse(url=f"/member/{member_id}", status_code=303)

@app.post("/notifications/{nid}/read")
async def mark_notification_read(request: Request, nid: int):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=303)
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("UPDATE notifications SET read_at = CURRENT_TIMESTAMP WHERE id = ? AND recipient_id = ?", (nid, user_id))
        await db.commit()
    return RedirectResponse(url="/dashboard", status_code=303)

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)

# ----------------- 后台管理功能 -----------------

@app.get("/admin", response_class=HTMLResponse)
async def admin_index(request: Request):
    if not request.session.get("is_admin"):
        return RedirectResponse(url="/admin/login")
    return RedirectResponse(url="/admin/dashboard")

@app.get("/admin/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    return templates.TemplateResponse("admin_login.html", {"request": request})

@app.post("/admin/login")
async def admin_login(request: Request, password: str = Form(...)):
    if password == ADMIN_PASSWORD:
        request.session["is_admin"] = True
        return RedirectResponse(url="/admin/dashboard", status_code=303)
    return templates.TemplateResponse("admin_login.html", {"request": request, "error": "密码错误"})

@app.get("/admin/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    if not request.session.get("is_admin"):
        return RedirectResponse(url="/admin/login")
        
    async with aiosqlite.connect(DATABASE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users ORDER BY id DESC") as cursor:
            users = await cursor.fetchall()
            
    return templates.TemplateResponse("admin_dashboard.html", {
        "request": request,
        "users": users
    })

@app.post("/admin/verify/{user_id}")
async def admin_verify_user(request: Request, user_id: int):
    if not request.session.get("is_admin"):
        return RedirectResponse(url="/admin/login")
        
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("UPDATE users SET is_verified = 1 WHERE id = ?", (user_id,))
        await db.commit()
        
    return RedirectResponse(url="/admin/dashboard", status_code=303)

@app.get("/admin/private_image/{filename}")
async def get_private_image(request: Request, filename: str):
    # 安全检查：只有管理员能访问
    if not request.session.get("is_admin"):
        raise HTTPException(status_code=403, detail="未授权访问")
    
    file_path = f"{PRIVATE_UPLOAD_DIR}/id_cards/{filename}"
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="文件不存在")
        
    return FileResponse(file_path)

@app.get("/admin/asset_image/{filename}")
async def get_asset_image(request: Request, filename: str):
    # 安全检查：只有管理员能访问
    if not request.session.get("is_admin"):
        raise HTTPException(status_code=403, detail="未授权访问")
    
    file_path = f"{PRIVATE_UPLOAD_DIR}/assets/{filename}"
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="文件不存在")
        
    return FileResponse(file_path)

if __name__ == "__main__":
    is_dev = os.getenv("ENV") != "production"
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=is_dev)

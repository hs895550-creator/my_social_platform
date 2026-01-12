import uvicorn
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel
import aiosqlite
import os
import random
import shutil
import uuid
import traceback

try:
    from uni.client import UniClient
except ImportError:
    print("WARNING: Could not import UniClient. SMS functionality will fail.")
    UniClient = None

app = FastAPI()

@app.get("/health")
async def health_check():
    return {"status": "ok"}

# 配置
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-here")  # 生产环境请使用环境变量覆盖
# UniSMS 配置
UNISMS_ACCESS_KEY_ID = "kFWQ7AsDxdxARQSpaXZQx1uiKdNBWn8fx7kXgPAMAFqXvXiXP"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "social.db")
STATIC_DIR = os.path.join(BASE_DIR, "static")
UPLOAD_DIR = os.path.join(STATIC_DIR, "uploads")
PRIVATE_UPLOAD_DIR = os.path.join(BASE_DIR, "private_uploads")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")  # 简单演示用管理员密码
ADMIN_PREFIX = "/admin_secure_x9z"  # 后台安全路径前缀

# 模拟短信验证码存储 {phone: code}
SMS_CODES = {}

# 确保上传目录存在
os.makedirs(os.path.join(UPLOAD_DIR, "avatars"), exist_ok=True)
os.makedirs(os.path.join(PRIVATE_UPLOAD_DIR, "id_cards"), exist_ok=True)
os.makedirs(os.path.join(PRIVATE_UPLOAD_DIR, "assets"), exist_ok=True)

# 挂载静态文件
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# 添加 Session 中间件用于保持登录状态
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

# 模板引擎
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# --- 优先路由：后台入口重定向 ---
# 必须放在最前面，防止被静态文件或其他通配符拦截
@app.get("/admin", include_in_schema=False)
@app.get("/admin/", include_in_schema=False)
async def admin_alias_root(request: Request):
    """
    重定向 /admin 到真正的后台登录页。
    """
    print(f"Redirecting /admin to {ADMIN_PREFIX}/login")
    return RedirectResponse(url=f"{ADMIN_PREFIX}/login", status_code=303)

@app.get("/admin/login", include_in_schema=False)
async def admin_login_alias_root(request: Request):
    return RedirectResponse(url=f"{ADMIN_PREFIX}/login", status_code=303)
# --------------------------------

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
                id_card_front_path TEXT,
                id_card_back_path TEXT,
                id_card_handheld_path TEXT,
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
                status TEXT DEFAULT 'pending_upload', -- pending_upload, pending_approval, active, rejected
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
            "avatar_path TEXT", "id_card_front_path TEXT", "id_card_back_path TEXT", "id_card_handheld_path TEXT",
            "is_verified BOOLEAN DEFAULT 0",
            "ip_address TEXT", "name TEXT", "dob TEXT", "state TEXT", "city TEXT",
            "hair_color TEXT", "eye_color TEXT", "height TEXT", "weight TEXT",
            "marital_status TEXT", "smoking TEXT", "match_gender TEXT",
            "match_age_min INTEGER", "match_age_max INTEGER",
            "asset_proof_path TEXT", "is_ai BOOLEAN DEFAULT 0", "last_active_at TIMESTAMP",
            "status TEXT DEFAULT 'pending_upload'"
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
    print("Starting up application...")
    try:
        await init_db()
        print("Database initialized.")
    except Exception as e:
        print(f"Database initialization failed: {e}")
        traceback.print_exc()

    # Skip AI bot check for now to prevent startup hang
    # async with aiosqlite.connect(DATABASE) as db:
    #     async with db.execute("SELECT id FROM users WHERE is_ai = 1 LIMIT 1") as cursor:
    #         bot = await cursor.fetchone()
    #     if not bot:
    #         await db.execute(
    #             "INSERT INTO users (phone, password, gender, age_range, country, name, is_verified, is_ai, status) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 'active')",
    #             ("BOT", "bot", None, None, None, "系统助手", 1)
    #         )
    #         await db.commit()

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
    user_id = request.session.get("user_id")
    if not user_id:
        return templates.TemplateResponse("index.html", {"request": request})

    async with aiosqlite.connect(DATABASE) as db:
        async with db.execute("SELECT status FROM users WHERE id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()

    if not row:
        request.session.clear()
        return templates.TemplateResponse("index.html", {"request": request})

    user_status = row[0]
    if user_status == "active":
        return RedirectResponse(url="/dashboard", status_code=303)
    if user_status in ("pending_approval", "rejected"):
        return RedirectResponse(url="/status_check", status_code=303)
    return RedirectResponse(url="/verification", status_code=303)

class PhoneRequest(BaseModel):
    phone: str

@app.post("/send_code")
async def send_code(item: PhoneRequest):
    code = str(random.randint(100000, 999999))
    SMS_CODES[item.phone] = code
    print(f"DEBUG: SMS Code for {item.phone} is {code}")

    # UniSMS 发送逻辑
    access_key_secret = os.getenv("UNISMS_ACCESS_KEY_SECRET")
    
    # 尝试发送短信（支持简单模式/无密钥模式）
    try:
        # 如果 access_key_secret 为 None，UniClient 会自动使用简单模式（不签名）
        client = UniClient(UNISMS_ACCESS_KEY_ID, access_key_secret)
        # 修正：使用 client.messages.send 而不是 client.send
        res = client.messages.send({
            "to": item.phone,
            "signature": "GlobalAsianElite",  # 请确保在 UniSMS 后台申请了此签名
            "templateId": "pub_verif_basic2", # 请确保使用了正确的模板ID，或改为您的自定义模板ID
            "data": {"code": code}
        })
        print(f"DEBUG: UniSMS Response: {res}")
        
        # 检查响应内容
        # UniResponse 对象通常有 code, message, data 属性
        if getattr(res, 'code', '0') != '0':
             error_msg = getattr(res, 'message', str(res))
             print(f"WARNING: UniSMS API returned error: {error_msg}")
             raise Exception(f"API Error: {error_msg}")

    except Exception as e:
        print(f"ERROR: UniSMS send failed: {e}")
        # 发送失败，转入模拟模式，但在消息中提示错误原因
        return {
            "success": True, 
            "message": f"短信发送失败(错误:{str(e)})，已转入模拟模式。验证码: {code}", 
            "debug_code": code
        }

    # 发送成功
    return {"success": True, "message": "验证码已发送", "debug_code": code}

@app.post("/register")
async def register(
    request: Request,
    phone: str = Form(...),
    code: str = Form(...),
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

    # 验证短信验证码
    if SMS_CODES.get(phone) != code:
        return templates.TemplateResponse("index.html", {
            "request": request,
            "error": "验证码错误或已失效。",
            "active_tab": "register"
        })

    # 验证通过后清除验证码
    SMS_CODES.pop(phone, None)

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
        return RedirectResponse(url="/verification", status_code=303)
        
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
            
        if user["status"] != "active":
            if user["status"] in ("pending_approval", "rejected"):
                return RedirectResponse(url="/status_check", status_code=303)
            return RedirectResponse(url="/verification", status_code=303)
            
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
            
        if user["status"] != "active":
            if user["status"] in ("pending_approval", "rejected"):
                return RedirectResponse(url="/status_check", status_code=303)
            return RedirectResponse(url="/verification", status_code=303)

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
    id_card_front: UploadFile = File(None),
    id_card_back: UploadFile = File(None),
    id_card_handheld: UploadFile = File(None),
    asset_proof: UploadFile = File(None)
):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=303)

    avatar_path = None
    id_card_front_path = None
    id_card_back_path = None
    id_card_handheld_path = None
    asset_proof_path = None

    # 处理头像上传 (公开)
    if avatar and avatar.filename:
        ext = os.path.splitext(avatar.filename)[1]
        filename = f"{user_id}_{uuid.uuid4()}{ext}"
        filepath = os.path.join(UPLOAD_DIR, filename)
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(avatar.file, buffer)
        avatar_path = f"/static/uploads/{filename}"

    # 处理证件上传 (私密) - 正面
    if id_card_front and id_card_front.filename:
        ext = os.path.splitext(id_card_front.filename)[1]
        filename = f"{user_id}_front_{uuid.uuid4()}{ext}"
        filepath = os.path.join(PRIVATE_UPLOAD_DIR, "id_cards", filename)
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(id_card_front.file, buffer)
        id_card_front_path = os.path.relpath(filepath, BASE_DIR)

    # 处理证件上传 (私密) - 反面
    if id_card_back and id_card_back.filename:
        ext = os.path.splitext(id_card_back.filename)[1]
        filename = f"{user_id}_back_{uuid.uuid4()}{ext}"
        filepath = os.path.join(PRIVATE_UPLOAD_DIR, "id_cards", filename)
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(id_card_back.file, buffer)
        id_card_back_path = os.path.relpath(filepath, BASE_DIR)

    # 处理证件上传 (私密) - 手持
    if id_card_handheld and id_card_handheld.filename:
        ext = os.path.splitext(id_card_handheld.filename)[1]
        filename = f"{user_id}_handheld_{uuid.uuid4()}{ext}"
        filepath = os.path.join(PRIVATE_UPLOAD_DIR, "id_cards", filename)
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(id_card_handheld.file, buffer)
        id_card_handheld_path = os.path.relpath(filepath, BASE_DIR)
        
    # 处理资产证明上传 (私密)
    if asset_proof and asset_proof.filename:
        ext = os.path.splitext(asset_proof.filename)[1]
        filename = f"{user_id}_{uuid.uuid4()}{ext}"
        asset_dir = os.path.join(PRIVATE_UPLOAD_DIR, "assets")
        os.makedirs(asset_dir, exist_ok=True)
        filepath = os.path.join(asset_dir, filename)
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(asset_proof.file, buffer)
        asset_proof_path = os.path.relpath(filepath, BASE_DIR)

    async with aiosqlite.connect(DATABASE) as db:
        if avatar_path:
            await db.execute("UPDATE users SET avatar_path = ? WHERE id = ?", (avatar_path, user_id))
        if id_card_front_path:
            await db.execute("UPDATE users SET id_card_front_path = ? WHERE id = ?", (id_card_front_path, user_id))
        if id_card_back_path:
            await db.execute("UPDATE users SET id_card_back_path = ? WHERE id = ?", (id_card_back_path, user_id))
        if id_card_handheld_path:
            await db.execute("UPDATE users SET id_card_handheld_path = ? WHERE id = ?", (id_card_handheld_path, user_id))
        if asset_proof_path:
            await db.execute("UPDATE users SET asset_proof_path = ? WHERE id = ?", (asset_proof_path, user_id))

        async with db.execute(
            """
            SELECT id_card_front_path, id_card_back_path, id_card_handheld_path, asset_proof_path
            FROM users WHERE id = ?
            """,
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()

        if row and all(row):
            await db.execute("UPDATE users SET status = 'pending_approval' WHERE id = ?", (user_id,))
        else:
            await db.execute("UPDATE users SET status = 'pending_upload' WHERE id = ?", (user_id,))

        await db.commit()

    return RedirectResponse(url="/status_check", status_code=303)

@app.post("/photo/delete")
async def photo_delete(request: Request, photo_id: int = Form(...)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=303)
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("DELETE FROM user_photos WHERE id = ? AND user_id = ?", (photo_id, user_id))
        await db.commit()
    return RedirectResponse(url="/profile/photos", status_code=303)

@app.post("/photo/upload")
async def photo_upload(request: Request, photo: UploadFile = File(...)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=303)

    if not photo or not photo.filename:
        return RedirectResponse(url="/profile/photos", status_code=303)

    ext = os.path.splitext(photo.filename)[1]
    filename = f"{user_id}_{uuid.uuid4()}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)
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

        if user["status"] != "active":
            if user["status"] in ("pending_approval", "rejected"):
                return RedirectResponse(url="/status_check", status_code=303)
            return RedirectResponse(url="/verification", status_code=303)

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
        db.row_factory = aiosqlite.Row
        # 检查当前用户状态
        async with db.execute("SELECT status FROM users WHERE id = ?", (user_id,)) as cursor:
            current_user = await cursor.fetchone()
        
        if current_user["status"] != "active":
            if current_user["status"] in ("pending_approval", "rejected"):
                return RedirectResponse(url="/status_check", status_code=303)
            return RedirectResponse(url="/verification", status_code=303)

        await db.execute("UPDATE users SET last_active_at = CURRENT_TIMESTAMP WHERE id = ?", (user_id,))
        await db.commit()
        
        async with db.execute("SELECT id, name, gender, age_range, country, city, avatar_path, is_verified, is_ai FROM users WHERE id = ?", (member_id,)) as cursor:
            member = await cursor.fetchone()
        if not member:
            raise HTTPException(status_code=404, detail="用户不存在")
        if user_id != member_id:
            await db.execute("INSERT INTO profile_views (viewer_id, viewed_id) VALUES (?, ?)", (user_id, member_id))
            await db.execute("INSERT INTO notifications (recipient_id, actor_id, type) VALUES (?, ?, 'view')", (member_id, user_id))
            await db.commit()
    return templates.TemplateResponse("member.html", {"request": request, "member": member})

@app.get(f"{ADMIN_PREFIX}/users", response_class=HTMLResponse)
async def admin_users(request: Request):
    return RedirectResponse(url=f"{ADMIN_PREFIX}/dashboard", status_code=303)

@app.get("/chat/{peer_id}", response_class=HTMLResponse)
async def chat_page(request: Request, peer_id: int):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=303)
    async with aiosqlite.connect(DATABASE) as db:
        db.row_factory = aiosqlite.Row
        # 检查当前用户状态
        async with db.execute("SELECT status FROM users WHERE id = ?", (user_id,)) as cursor:
            current_user = await cursor.fetchone()
        
        if current_user["status"] != "active":
            if current_user["status"] in ("pending_approval", "rejected"):
                return RedirectResponse(url="/status_check", status_code=303)
            return RedirectResponse(url="/verification", status_code=303)

        await db.execute("UPDATE users SET last_active_at = CURRENT_TIMESTAMP WHERE id = ?", (user_id,))
        await db.commit()
        
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
        # 检查状态
        async with db.execute("SELECT status FROM users WHERE id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row and row[0] != 'active':
                return RedirectResponse(url="/status_check" if row[0] in ('pending_approval', 'rejected') else "/verification", status_code=303)

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
        
        # 检查状态
        async with db.execute("SELECT status FROM users WHERE id = ?", (user_id,)) as cursor:
            current_user = await cursor.fetchone()
        if current_user["status"] != "active":
             raise HTTPException(status_code=403, detail="Account not active")

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
        # 检查状态
        async with db.execute("SELECT status FROM users WHERE id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row and row[0] != 'active':
                 return {"ok": False, "error": "Account not active"}

        await db.execute("INSERT INTO messages (sender_id, receiver_id, content) VALUES (?, ?, ?)", (user_id, peer_id, content.strip()))
        await db.commit()
    return {"ok": True}

@app.get("/status_check", response_class=HTMLResponse)
async def status_check(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/")
        
    async with aiosqlite.connect(DATABASE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE id = ?", (user_id,)) as cursor:
            user = await cursor.fetchone()
            
    if not user:
        request.session.clear()
        return RedirectResponse(url="/")
        
    if user["status"] == "active":
        return RedirectResponse(url="/dashboard", status_code=303)
        
    if user["status"] == "pending_upload":
        return RedirectResponse(url="/verification", status_code=303)

    return templates.TemplateResponse("status_check.html", {"request": request, "user": user})

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/", status_code=303)
    
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("UPDATE users SET last_active_at = CURRENT_TIMESTAMP WHERE id = ?", (user_id,))
        await db.commit()
        # 获取当前用户信息
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE id = ?", (user_id,)) as cursor:
            current_user = await cursor.fetchone()

        # 强制状态检查
        if not current_user:
             request.session.clear()
             return RedirectResponse(url="/", status_code=303)
        
        # 严格模式：非 active 状态一律禁止访问
        if current_user["status"] != "active":
            if current_user["status"] in ("pending_approval", "rejected"):
                return RedirectResponse(url="/status_check", status_code=303)
            else:
                # 包括 pending_upload 和可能存在的 NULL (老用户)
                return RedirectResponse(url="/verification", status_code=303)

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
        
        # 检查状态
        async with db.execute("SELECT status FROM users WHERE id = ?", (user_id,)) as cursor:
            current_user = await cursor.fetchone()
        if current_user["status"] != "active":
            if current_user["status"] in ("pending_approval", "rejected"):
                return RedirectResponse(url="/status_check", status_code=303)
            return RedirectResponse(url="/verification", status_code=303)

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

@app.get("/private_file")
async def get_private_file(request: Request, path: str):
    user_id = request.session.get("user_id")
    is_admin = request.session.get("is_admin")
    
    if not user_id and not is_admin:
        raise HTTPException(status_code=403, detail="Not authenticated")
        
    if ".." in path:
        raise HTTPException(status_code=403, detail="Invalid path")

    abs_path = os.path.abspath(os.path.join(BASE_DIR, path))
    if os.path.commonpath([abs_path, PRIVATE_UPLOAD_DIR]) != PRIVATE_UPLOAD_DIR:
        raise HTTPException(status_code=403, detail="Invalid path")

    if not os.path.exists(abs_path):
        raise HTTPException(status_code=404, detail="File not found")
        
    # 权限检查 (简单实现: 管理员可看所有，普通用户只能看自己的)
    # 通过文件名判断: {user_id}_...
    if not is_admin:
        filename = os.path.basename(abs_path)
        file_user_id = filename.split("_")[0]
        if str(user_id) != file_user_id:
             raise HTTPException(status_code=403, detail="Permission denied")

    return FileResponse(abs_path)

# ----------------- 后台管理功能 -----------------

@app.get(f"{ADMIN_PREFIX}", response_class=HTMLResponse)
async def admin_index(request: Request):
    if not request.session.get("is_admin"):
        return RedirectResponse(url=f"{ADMIN_PREFIX}/login")
    return RedirectResponse(url=f"{ADMIN_PREFIX}/dashboard")

@app.get(f"{ADMIN_PREFIX}/login", response_class=HTMLResponse)
async def admin_login_page(request: Request):
    return templates.TemplateResponse("admin_login.html", {"request": request, "admin_prefix": ADMIN_PREFIX})

@app.post(f"{ADMIN_PREFIX}/login")
async def admin_login(request: Request, password: str = Form(...)):
    if password == ADMIN_PASSWORD:
        request.session["is_admin"] = True
        return RedirectResponse(url=f"{ADMIN_PREFIX}/dashboard", status_code=303)
    return templates.TemplateResponse("admin_login.html", {"request": request, "error": "密码错误", "admin_prefix": ADMIN_PREFIX})

@app.get(f"{ADMIN_PREFIX}/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request, status: str = "pending_approval"):
    if not request.session.get("is_admin"):
        return RedirectResponse(url=f"{ADMIN_PREFIX}/login")
        
    async with aiosqlite.connect(DATABASE) as db:
        db.row_factory = aiosqlite.Row
        if status == "all":
            query = "SELECT * FROM users ORDER BY id DESC"
            params = ()
        else:
            query = "SELECT * FROM users WHERE status = ? ORDER BY created_at DESC"
            params = (status,)
            
        async with db.execute(query, params) as cursor:
            users = await cursor.fetchall()
            
    return templates.TemplateResponse("admin_dashboard.html", {
        "request": request,
        "users": users,
        "current_status": status,
        "admin_prefix": ADMIN_PREFIX
    })


@app.get(f"{ADMIN_PREFIX}/debug")
async def admin_debug(request: Request):
    if not request.session.get("is_admin"):
        return RedirectResponse(url=f"{ADMIN_PREFIX}/login", status_code=303)

    async with aiosqlite.connect(DATABASE) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c:
            total = (await c.fetchone())[0]

        by_status = {}
        async with db.execute("SELECT status, COUNT(*) FROM users GROUP BY status") as cur:
            rows = await cur.fetchall()
        for s, n in rows:
            by_status[s] = n

        async with db.execute(
            """
            SELECT COUNT(*)
            FROM users
            WHERE id_card_front_path IS NOT NULL
              AND id_card_back_path IS NOT NULL
              AND id_card_handheld_path IS NOT NULL
              AND asset_proof_path IS NOT NULL
            """
        ) as c2:
            docs_complete = (await c2.fetchone())[0]

    return JSONResponse(
        {
            "base_dir": BASE_DIR,
            "database": DATABASE,
            "total_users": total,
            "users_by_status": by_status,
            "docs_complete_users": docs_complete,
        }
    )

@app.post(f"{ADMIN_PREFIX}/approve/{{user_id}}")
async def admin_approve(request: Request, user_id: int):
    if not request.session.get("is_admin"):
        return RedirectResponse(url=f"{ADMIN_PREFIX}/login", status_code=303)
        
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("UPDATE users SET status = 'active', is_verified = 1 WHERE id = ?", (user_id,))
        await db.commit()
        
    return RedirectResponse(url=f"{ADMIN_PREFIX}/dashboard", status_code=303)

@app.post(f"{ADMIN_PREFIX}/reject/{{user_id}}")
async def admin_reject(request: Request, user_id: int):
    if not request.session.get("is_admin"):
        return RedirectResponse(url=f"{ADMIN_PREFIX}/login", status_code=303)
        
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("UPDATE users SET status = 'rejected' WHERE id = ?", (user_id,))
        await db.commit()
        
    return RedirectResponse(url=f"{ADMIN_PREFIX}/dashboard", status_code=303)

@app.post(f"{ADMIN_PREFIX}/verify/{{user_id}}")
async def admin_verify_user(request: Request, user_id: int):
    if not request.session.get("is_admin"):
        return RedirectResponse(url=f"{ADMIN_PREFIX}/login")
        
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("UPDATE users SET is_verified = 1 WHERE id = ?", (user_id,))
        await db.commit()
        
    return RedirectResponse(url=f"{ADMIN_PREFIX}/dashboard", status_code=303)

@app.get("/private_uploads/{category}/{filename}")
async def get_private_file(request: Request, category: str, filename: str):
    # 安全检查：只有管理员能访问
    if not request.session.get("is_admin"):
        raise HTTPException(status_code=403, detail="未授权访问")
    
    # 防止路径遍历
    if ".." in category or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid path")

    file_path = os.path.join(PRIVATE_UPLOAD_DIR, category, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="文件不存在")
        
    return FileResponse(file_path)

if __name__ == "__main__":
    # 强制关闭 reload 以确保生产环境稳定
    # is_dev = os.getenv("ENV") != "production"
    port = int(os.getenv("PORT", 8080))
    print(f"Server is starting on port {port}...")
    try:
        uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
    except Exception as e:
        print(f"Server failed to start: {e}")

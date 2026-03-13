from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_from_directory
import sqlite3
from datetime import datetime, timedelta
import os
import json
import time
import threading
from werkzeug.utils import secure_filename
from flask_socketio import SocketIO, join_room

app = Flask(__name__)
app.secret_key = 'uma-secret-key-123'

DB_PATH = 'uma_draft.db'
socketio = SocketIO(app, cors_allowed_origins="*")


@app.context_processor
def utility_processor():
    """Cho phép dùng now() trong template Jinja."""
    return {'now': datetime.now}

# Timer thread health
TIMER_STARTED_AT = None
TIMER_LAST_TICK_AT = None
TIMER_LAST_ERROR = None

def load_uma_data():
    """Đọc dữ liệu mã nương từ file JSON bao gồm tất cả outfits"""
    try:
        file_path = os.path.join('database', 'uma_database.json')
        print(f"Đang đọc file: {file_path}")

        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            characters = data.get('characters', [])
            uma_list = []

            for char in characters:
                character_id = str(char['id'])
                character_name = char.get('name_jp') or char.get('name') or 'Unknown'
                character_name_en = char.get('name_en') or char.get('name') or 'Unknown'

                # Nếu có outfits, tạo một mục cho mỗi outfit
                if char.get('outfits') and len(char.get('outfits')) > 0:
                    for outfit in char['outfits']:
                        outfit_id = str(outfit.get('id', character_id))
                        outfit_name = outfit.get('name', 'Default Outfit')

                        # Xử lý đường dẫn ảnh icon
                        icon_path = outfit.get('icon', '')
                        if icon_path and 'thunbnails' in icon_path:
                            icon_path = icon_path.replace('thunbnails', 'thumbnails')
                        if icon_path and not icon_path.startswith('/'):
                            icon_path = '/' + icon_path

                        uma_list.append(
                            {
                                'id': outfit_id,
                                'character_id': character_id,
                                'name': f"{character_name} - {outfit_name}",
                                'name_en': f"{character_name_en} - {outfit_name}",
                                'simple_name': character_name,
                                'simple_name_en': character_name_en,
                                'rarity': outfit.get('rarity', 3),
                                'image': icon_path,
                                'running_style': outfit.get('running_style', 0),
                                'outfit_name': outfit_name,
                            }
                        )
                else:
                    # Không có outfits, dùng thumbnail
                    thumb_path = char.get('thumbnail', '')
                    if thumb_path and 'thunbnails' in thumb_path:
                        thumb_path = thumb_path.replace('thunbnails', 'thumbnails')
                    if thumb_path and not thumb_path.startswith('/'):
                        thumb_path = '/' + thumb_path

                    uma_list.append(
                        {
                            'id': character_id,
                            'character_id': character_id,
                            'name': character_name,
                            'name_en': character_name_en,
                            'simple_name': character_name,
                            'simple_name_en': character_name_en,
                            'rarity': 3,
                            'image': thumb_path,
                            'running_style': 0,
                            'outfit_name': 'Default',
                        }
                    )

            print(f"Đã load {len(uma_list)} outfits từ {len(characters)} nhân vật")
            return uma_list

    except Exception as e:
        print(f"Lỗi đọc file: {e}")
        import traceback
        traceback.print_exc()
        return []


# Load dữ liệu
UMA_LIST = load_uma_data()
print(f"📊 UMA_LIST cuối cùng có {len(UMA_LIST)} phần tử")


@app.route('/assets/<path:filename>')
def serve_assets(filename):
    """Phục vụ file từ thư mục assets - hỗ trợ cả icons và thumbnails"""
    import os
    current_dir = os.path.dirname(os.path.abspath(__file__))

    # Danh sách các thư mục cần tìm
    search_paths = [
        os.path.join(current_dir, 'assets'),               # gốc
        os.path.join(current_dir, 'assets', 'icons'),      # trong icons
        os.path.join(current_dir, 'assets', 'thumbnails'), # trong thumbnails
    ]

    # Tách tên file từ path (ví dụ: "icons/103302.png" -> "103302.png")
    basename = os.path.basename(filename)

    # Thử tìm trong từng thư mục
    for base_path in search_paths:
        # Thử với tên file gốc
        full_path = os.path.join(base_path, basename)
        if os.path.exists(full_path):
            print(f"✅ Found: {full_path}")
            return send_from_directory(base_path, basename)

        # Thử với đường dẫn đầy đủ (nếu filename đã bao gồm thư mục con)
        full_path = os.path.join(base_path, filename)
        if os.path.exists(full_path):
            print(f"✅ Found: {full_path}")
            return send_from_directory(base_path, filename)

    # Không tìm thấy
    print(f"❌ Not found: {filename}")
    return "File not found", 404


@app.route('/debug/assets')
def debug_assets():
    """Liệt kê nội dung thư mục assets"""
    import os
    current_dir = os.path.dirname(os.path.abspath(__file__))
    assets_dir = os.path.join(current_dir, 'assets')

    result = {
        'current_dir': current_dir,
        'assets_dir': assets_dir,
        'assets_exists': os.path.exists(assets_dir),
        'contents': {},
    }

    if os.path.exists(assets_dir):
        try:
            # Liệt kê các thư mục con
            for item in os.listdir(assets_dir):
                item_path = os.path.join(assets_dir, item)
                if os.path.isdir(item_path):
                    # Liệt kê file trong thư mục con
                    try:
                        files = os.listdir(item_path)[:10]  # chỉ lấy 10 file đầu
                        result['contents'][item] = {
                            'path': item_path,
                            'file_count': len(os.listdir(item_path)),
                            'sample_files': files,
                        }
                    except Exception:
                        result['contents'][item] = f'Error reading directory: {item}'
                else:
                    result['contents'][item] = 'file'
        except Exception as e:
            result['error'] = str(e)
    else:
        # Thử tìm assets ở các vị trí khác
        alt_paths = [
            os.path.join(current_dir, 'static', 'assets'),
            os.path.join(current_dir, '..', 'assets'),
            r'D:\assets',  # Thử đường dẫn tuyệt đối
        ]
        result['alternative_paths'] = {}
        for alt in alt_paths:
            result['alternative_paths'][alt] = os.path.exists(alt)

    return jsonify(result)

# Cấu hình upload
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max

# Tạo thư mục cần thiết
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs('templates', exist_ok=True)
os.makedirs('templates/trainer', exist_ok=True)


def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn


def _ensure_users_columns(conn: sqlite3.Connection):
    cols = {row['name'] for row in conn.execute("PRAGMA table_info(users)").fetchall()}

    # Migration từ bản cũ (chưa có lobby_id)
    if 'lobby_id' not in cols:
        conn.execute('ALTER TABLE users ADD COLUMN lobby_id INTEGER')

    # Đảm bảo có đủ field theo schema mới (nếu DB đã tồn tại và bị thiếu cột)
    if 'image_path' not in cols:
        conn.execute('ALTER TABLE users ADD COLUMN image_path TEXT')
    if 'created_at' not in cols:
        conn.execute('ALTER TABLE users ADD COLUMN created_at TIMESTAMP')
    if 'display_name' not in cols:
        conn.execute('ALTER TABLE users ADD COLUMN display_name TEXT')


# Tạo database
def init_db():
    conn = get_conn()

    # Tạo bảng users
    conn.execute(
        '''CREATE TABLE IF NOT EXISTS users
                    (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     facebook_link TEXT UNIQUE,
                     display_name TEXT,
                     role TEXT,
                     image_path TEXT,
                     lobby_id INTEGER,
                     created_at TIMESTAMP)'''
    )

    _ensure_users_columns(conn)

    # Tạo bảng lobbies
    conn.execute(
        '''CREATE TABLE IF NOT EXISTS lobbies
                    (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     name TEXT NOT NULL,
                     max_players INTEGER DEFAULT 4,
                     status TEXT DEFAULT 'waiting',
                     created_by INTEGER,
                     created_at TIMESTAMP,
                     FOREIGN KEY (created_by) REFERENCES users (id))'''
    )

    # Tạo bảng lobby_players
    conn.execute(
        '''CREATE TABLE IF NOT EXISTS lobby_players
                    (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     lobby_id INTEGER,
                     user_id INTEGER,
                     joined_at TIMESTAMP,
                     FOREIGN KEY (lobby_id) REFERENCES lobbies (id),
                     FOREIGN KEY (user_id) REFERENCES users (id),
                     UNIQUE(lobby_id, user_id))'''
    )

    # State banpick (đơn giản hoá: lưu JSON dạng text)
    conn.execute(
        '''CREATE TABLE IF NOT EXISTS banpick_state
                    (lobby_id INTEGER PRIMARY KEY,
                     timer_end TIMESTAMP,
                     started_at TIMESTAMP,
                     status TEXT,
                     current_phase TEXT,
                     current_team INTEGER,
                     current_round INTEGER,
                     bans TEXT,
                     picks TEXT,
                     FOREIGN KEY (lobby_id) REFERENCES lobbies (id) ON DELETE CASCADE)'''
    )

    # Bảng lưu team của mỗi người chơi (do admin phân)
    conn.execute(
        '''CREATE TABLE IF NOT EXISTS player_teams
                (id INTEGER PRIMARY KEY AUTOINCREMENT,
                 lobby_id INTEGER,
                 user_id INTEGER UNIQUE,
                 team_number INTEGER,
                 FOREIGN KEY (lobby_id) REFERENCES lobbies (id),
                 FOREIGN KEY (user_id) REFERENCES users (id))'''
    )

    # Bảng lưu lượt ban/pick của mỗi người
    conn.execute(
        '''CREATE TABLE IF NOT EXISTS player_actions
                (id INTEGER PRIMARY KEY AUTOINCREMENT,
                 lobby_id INTEGER,
                 user_id INTEGER,
                 action_type TEXT,
                 uma_id TEXT,
                 action_order INTEGER,
                 created_at TIMESTAMP,
                 FOREIGN KEY (lobby_id) REFERENCES lobbies (id),
                 FOREIGN KEY (user_id) REFERENCES users (id))'''
    )

    # Bảng lưu thứ tự lượt chơi
    conn.execute(
        '''CREATE TABLE IF NOT EXISTS player_turns
                (id INTEGER PRIMARY KEY AUTOINCREMENT,
                 lobby_id INTEGER,
                 turn_order INTEGER,
                 user_id INTEGER,
                 remaining_bans INTEGER DEFAULT 1,
                 remaining_picks INTEGER DEFAULT 3,
                 FOREIGN KEY (lobby_id) REFERENCES lobbies (id),
                 FOREIGN KEY (user_id) REFERENCES users (id))'''
    )

    # Bảng lưu seed (thứ tự) do trọng tài phân
    conn.execute(
        '''CREATE TABLE IF NOT EXISTS player_seeds
                (id INTEGER PRIMARY KEY AUTOINCREMENT,
                 lobby_id INTEGER,
                 user_id INTEGER UNIQUE,
                 seed_number INTEGER,
                 created_at TIMESTAMP,
                 FOREIGN KEY (lobby_id) REFERENCES lobbies (id),
                 FOREIGN KEY (user_id) REFERENCES users (id))'''
    )

    conn.commit()
    conn.close()
    print("Database created!")


init_db()


@socketio.on('join')
def on_join(data):
    lobby_id = data.get('lobby_id')
    if lobby_id is None:
        return
    join_room(f"lobby_{int(lobby_id)}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        facebook_link = request.form['facebook_link']
        role = request.form['role']
        
        conn = get_conn()
        
        # Kiểm tra user đã tồn tại chưa
        user = conn.execute('SELECT * FROM users WHERE facebook_link = ?', 
                           [facebook_link]).fetchone()
        
        if user:
            # Đăng nhập user cũ
            session['user_id'] = user['id']
            session['role'] = user['role']
            session['display_name'] = user['display_name']
            flash(f'Chào mừng {user["role"]} quay lại!', 'success')
            conn.close()
            
            # Chuyển hướng theo role
            if user['role'] == 'admin':
                return redirect(url_for('admin_page'))
            elif user['role'] == 'referee':
                return redirect(url_for('referee_page'))
            else:
                # Kiểm tra đã upload ảnh chưa
                if user['image_path']:
                    return redirect(url_for('trainer_page'))
                else:
                    return redirect(url_for('upload_image'))
        else:
            # Tạo user mới
            cursor = conn.execute('''INSERT INTO users (facebook_link, role, created_at)
                                   VALUES (?, ?, ?)''',
                                [facebook_link, role, datetime.now()])
            user_id = cursor.lastrowid
            conn.commit()
            conn.close()
            
            session['user_id'] = user_id
            session['role'] = role
            session['display_name'] = None
            flash('Đăng ký thành công!', 'success')
            
            # Trainer mới cần upload ảnh
            if role == 'trainer':
                return redirect(url_for('upload_image'))
            elif role == 'admin':
                return redirect(url_for('admin_page'))
            else:
                return redirect(url_for('referee_page'))
    
    return render_template('login.html')

@app.route('/upload-image', methods=['GET', 'POST'])
def upload_image():
    if 'user_id' not in session or session['role'] != 'trainer':
        flash('Vui lòng đăng nhập với vai trò Trainer!', 'error')
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        # Kiểm tra file
        if 'image' not in request.files:
            flash('Không có file nào được chọn', 'error')
            return redirect(request.url)
        
        file = request.files['image']
        if file.filename == '':
            flash('Vui lòng chọn file ảnh', 'error')
            return redirect(request.url)
        
        if file and allowed_file(file.filename):
            # Tạo tên file an toàn
            filename = secure_filename(f"user_{session['user_id']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(save_path)

            # Lưu trong DB theo format dùng cho url_for('static', filename=...)
            # Ví dụ: uploads/abc.png (không kèm 'static/' và dùng '/')
            db_image_path = f"uploads/{filename}"
            
            # Lưu vào database
            conn = get_conn()
            conn.execute('UPDATE users SET image_path = ? WHERE id = ?',
                        [db_image_path, session['user_id']])
            conn.commit()
            conn.close()
            
            flash('Upload ảnh thành công!', 'success')
            return redirect(url_for('trainer_page'))
        else:
            flash('Chỉ chấp nhận file ảnh (png, jpg, jpeg, gif)', 'error')
            return redirect(request.url)
    
    return render_template('trainer/upload.html')

@app.route('/admin')
def admin_page():
    if 'user_id' not in session or session['role'] != 'admin':
        flash('Bạn không có quyền truy cập!', 'error')
        return redirect(url_for('login'))
    
    # Lấy danh sách users
    conn = get_conn()

    users = conn.execute(
        '''SELECT u.*, l.name as lobby_name 
                           FROM users u 
                           LEFT JOIN lobbies l ON u.lobby_id = l.id
                           ORDER BY u.created_at DESC'''
    ).fetchall()

    # Lấy danh sách lobbies
    lobbies = conn.execute('SELECT * FROM lobbies ORDER BY created_at DESC').fetchall()

    # Đếm số người trong mỗi lobby
    lobby_counts = {}
    for lobby in lobbies:
        count = conn.execute(
            'SELECT COUNT(*) as count FROM lobby_players WHERE lobby_id = ?',
            [lobby['id']],
        ).fetchone()
        lobby_counts[lobby['id']] = count['count']

    conn.close()

    return render_template('admin.html', users=users, lobbies=lobbies, lobby_counts=lobby_counts)


@app.route('/admin/create-lobby', methods=['POST'])
def create_lobby():
    if 'user_id' not in session or session['role'] != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403

    name = request.form.get('name')
    max_players = request.form.get('max_players', 4)

    if not name:
        flash('Vui lòng nhập tên lobby', 'error')
        return redirect(url_for('admin_page'))

    conn = get_conn()
    conn.execute(
        '''INSERT INTO lobbies (name, max_players, created_by, created_at) 
                    VALUES (?, ?, ?, ?)''',
        [name, max_players, session['user_id'], datetime.now()],
    )
    conn.commit()
    conn.close()

    flash(f'Đã tạo lobby "{name}" thành công!', 'success')
    return redirect(url_for('admin_page'))


@app.route('/admin/assign-user', methods=['POST'])
def assign_user():
    if 'user_id' not in session or session['role'] != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403

    user_id = request.form.get('user_id')
    lobby_id = request.form.get('lobby_id')

    if not user_id or not lobby_id:
        flash('Thiếu thông tin', 'error')
        return redirect(url_for('admin_page'))

    conn = get_conn()

    # Kiểm tra lobby còn chỗ không
    current_players = conn.execute(
        'SELECT COUNT(*) as count FROM lobby_players WHERE lobby_id = ?',
        [lobby_id],
    ).fetchone()
    lobby = conn.execute('SELECT max_players FROM lobbies WHERE id = ?', [lobby_id]).fetchone()

    if current_players['count'] >= lobby['max_players']:
        conn.close()
        flash('Lobby đã đầy!', 'error')
        return redirect(url_for('admin_page'))

    # Xóa khỏi lobby cũ nếu có
    old_lobby = conn.execute('SELECT lobby_id FROM users WHERE id = ?', [user_id]).fetchone()
    if old_lobby and old_lobby['lobby_id']:
        conn.execute('DELETE FROM lobby_players WHERE user_id = ?', [user_id])

    # Thêm vào lobby mới
    conn.execute(
        'INSERT OR IGNORE INTO lobby_players (lobby_id, user_id, joined_at) VALUES (?, ?, ?)',
        [lobby_id, user_id, datetime.now()],
    )

    # Cập nhật lobby_id cho user
    conn.execute('UPDATE users SET lobby_id = ? WHERE id = ?', [lobby_id, user_id])

    conn.commit()
    conn.close()

    flash('Đã phân người chơi thành công!', 'success')
    return redirect(url_for('admin_page'))


@app.route('/admin/remove-from-lobby/<int:user_id>', methods=['POST'])
def remove_from_lobby(user_id):
    if 'user_id' not in session or session['role'] != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403

    conn = get_conn()

    # Xóa khỏi lobby_players
    conn.execute('DELETE FROM lobby_players WHERE user_id = ?', [user_id])

    # Cập nhật lobby_id trong users
    conn.execute('UPDATE users SET lobby_id = NULL WHERE id = ?', [user_id])

    conn.commit()
    conn.close()

    flash('Đã xóa người chơi khỏi lobby!', 'success')
    return redirect(url_for('admin_page'))


@app.route('/admin/users')
def admin_users():
    """Trang quản lý người dùng (chi tiết hơn)."""
    if 'user_id' not in session or session['role'] != 'admin':
        flash('Bạn không có quyền truy cập!', 'error')
        return redirect(url_for('login'))

    conn = get_conn()

    users = conn.execute(
        '''SELECT u.*, l.name as lobby_name 
           FROM users u 
           LEFT JOIN lobbies l ON u.lobby_id = l.id
           ORDER BY u.created_at DESC'''
    ).fetchall()

    lobbies = conn.execute(
        'SELECT * FROM lobbies WHERE status = "waiting" ORDER BY created_at DESC'
    ).fetchall()

    conn.close()

    return render_template('admin/users.html', users=users, lobbies=lobbies)


@app.route('/admin/user/add', methods=['GET', 'POST'])
def admin_add_user():
    """Thêm người dùng mới."""
    if 'user_id' not in session or session['role'] != 'admin':
        flash('Bạn không có quyền!', 'error')
        return redirect(url_for('login'))

    if request.method == 'POST':
        facebook_link = request.form.get('facebook_link')
        display_name = request.form.get('display_name')
        role = request.form.get('role')
        lobby_id = request.form.get('lobby_id')

        if not facebook_link or not display_name or not role:
            flash('Vui lòng điền đầy đủ thông tin!', 'error')
            return redirect(url_for('admin_add_user'))

        conn = get_conn()

        try:
            existing = conn.execute(
                'SELECT id FROM users WHERE facebook_link = ?', [facebook_link]
            ).fetchone()
            if existing:
                flash('Facebook link đã tồn tại!', 'error')
                conn.close()
                return redirect(url_for('admin_add_user'))

            cursor = conn.execute(
                '''INSERT INTO users (facebook_link, display_name, role, created_at)
                   VALUES (?, ?, ?, ?)''',
                [facebook_link, display_name, role, datetime.now()],
            )
            user_id = cursor.lastrowid

            # Nếu có lobby_id và role là trainer, thêm vào lobby
            if lobby_id and role == 'trainer':
                players = conn.execute(
                    'SELECT COUNT(*) as cnt FROM lobby_players WHERE lobby_id = ?',
                    [lobby_id],
                ).fetchone()
                lobby = conn.execute(
                    'SELECT max_players FROM lobbies WHERE id = ?', [lobby_id]
                ).fetchone()

                if players and lobby and players['cnt'] < lobby['max_players']:
                    conn.execute(
                        'INSERT INTO lobby_players (lobby_id, user_id, joined_at) VALUES (?, ?, ?)',
                        [lobby_id, user_id, datetime.now()],
                    )
                    conn.execute(
                        'UPDATE users SET lobby_id = ? WHERE id = ?',
                        [lobby_id, user_id],
                    )

            conn.commit()
            flash(f'Đã thêm {role} thành công!', 'success')
        except Exception as e:
            conn.rollback()
            flash(f'Lỗi: {str(e)}', 'error')
        finally:
            conn.close()

        return redirect(url_for('admin_users'))

    # GET: hiển thị form thêm user
    conn = get_conn()
    lobbies = conn.execute(
        'SELECT * FROM lobbies WHERE status = "waiting" ORDER BY created_at DESC'
    ).fetchall()
    conn.close()

    return render_template('admin/user_form.html', lobbies=lobbies, action='add')


@app.route('/admin/user/edit/<int:user_id>', methods=['GET', 'POST'])
def admin_edit_user(user_id):
    """Sửa thông tin người dùng."""
    if 'user_id' not in session or session['role'] != 'admin':
        flash('Bạn không có quyền!', 'error')
        return redirect(url_for('login'))

    conn = get_conn()

    if request.method == 'POST':
        display_name = request.form.get('display_name')
        role = request.form.get('role')
        lobby_id = request.form.get('lobby_id')

        try:
            conn.execute(
                '''UPDATE users 
                   SET display_name = ?, role = ?
                   WHERE id = ?''',
                [display_name, role, user_id],
            )

            # Xử lý lobby
            old_lobby = conn.execute(
                'SELECT lobby_id FROM users WHERE id = ?', [user_id]
            ).fetchone()

            if old_lobby and old_lobby['lobby_id']:
                conn.execute('DELETE FROM lobby_players WHERE user_id = ?', [user_id])

            if lobby_id and role == 'trainer':
                players = conn.execute(
                    'SELECT COUNT(*) as cnt FROM lobby_players WHERE lobby_id = ?',
                    [lobby_id],
                ).fetchone()
                lobby = conn.execute(
                    'SELECT max_players FROM lobbies WHERE id = ?', [lobby_id]
                ).fetchone()

                if players and lobby and players['cnt'] < lobby['max_players']:
                    conn.execute(
                        'INSERT INTO lobby_players (lobby_id, user_id, joined_at) VALUES (?, ?, ?)',
                        [lobby_id, user_id, datetime.now()],
                    )
                    conn.execute(
                        'UPDATE users SET lobby_id = ? WHERE id = ?',
                        [lobby_id, user_id],
                    )
            else:
                conn.execute(
                    'UPDATE users SET lobby_id = NULL WHERE id = ?', [user_id]
                )

            conn.commit()
            flash('Cập nhật thông tin thành công!', 'success')
        except Exception as e:
            conn.rollback()
            flash(f'Lỗi: {str(e)}', 'error')
        finally:
            conn.close()

        return redirect(url_for('admin_users'))

    # GET: hiển thị form sửa
    user = conn.execute('SELECT * FROM users WHERE id = ?', [user_id]).fetchone()
    lobbies = conn.execute(
        'SELECT * FROM lobbies WHERE status = "waiting" ORDER BY created_at DESC'
    ).fetchall()
    conn.close()

    if not user:
        flash('Không tìm thấy người dùng!', 'error')
        return redirect(url_for('admin_users'))

    return render_template(
        'admin/user_form.html', user=user, lobbies=lobbies, action='edit'
    )


@app.route('/admin/user/delete/<int:user_id>', methods=['POST'])
def admin_delete_user(user_id):
    """Xóa người dùng."""
    if 'user_id' not in session or session['role'] != 'admin':
        flash('Bạn không có quyền!', 'error')
        return redirect(url_for('login'))

    conn = get_conn()

    try:
        if user_id == session['user_id']:
            flash('Không thể xóa tài khoản đang đăng nhập!', 'error')
            conn.close()
            return redirect(url_for('admin_users'))

        conn.execute('DELETE FROM lobby_players WHERE user_id = ?', [user_id])
        conn.execute('DELETE FROM player_seeds WHERE user_id = ?', [user_id])
        conn.execute('DELETE FROM player_turns WHERE user_id = ?', [user_id])
        conn.execute('DELETE FROM player_actions WHERE user_id = ?', [user_id])
        conn.execute('DELETE FROM users WHERE id = ?', [user_id])

        conn.commit()
        flash('Xóa người dùng thành công!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Lỗi: {str(e)}', 'error')
    finally:
        conn.close()

    return redirect(url_for('admin_users'))


@app.route('/admin/assign-teams/<int:lobby_id>', methods=['GET', 'POST'])
def assign_teams(lobby_id):
    """Admin phân team cho người chơi trong một lobby."""
    if 'user_id' not in session or session['role'] != 'admin':
        flash('Bạn không có quyền!', 'error')
        return redirect(url_for('login'))

    conn = get_conn()
    conn.row_factory = sqlite3.Row

    if request.method == 'POST':
        teams = request.form
        for key, team in teams.items():
            if key.startswith('user_') and team:
                uid = key.replace('user_', '')
                conn.execute(
                    '''INSERT OR REPLACE INTO player_teams (lobby_id, user_id, team_number)
                                VALUES (?, ?, ?)''',
                    [lobby_id, uid, int(team)],
                )
        conn.commit()
        conn.close()
        flash('Đã phân team thành công!', 'success')
        return redirect(url_for('lobby_page', lobby_id=lobby_id))

    # GET request - hiển thị form phân team
    players = conn.execute(
        '''SELECT u.* FROM users u
                              JOIN lobby_players lp ON u.id = lp.user_id
                              WHERE lp.lobby_id = ?''',
        [lobby_id],
    ).fetchall()

    # Kiểm tra đã có team chưa
    existing_teams = {}
    for player in players:
        team = conn.execute(
            'SELECT team_number FROM player_teams WHERE user_id = ? AND lobby_id = ?',
            [player['id'], lobby_id],
        ).fetchone()
        if team:
            existing_teams[player['id']] = team['team_number']

    conn.close()

    return render_template(
        'admin/assign_teams.html',
        lobby_id=lobby_id,
        players=players,
        existing_teams=existing_teams,
    )

@app.route('/admin/delete-lobby/<int:lobby_id>', methods=['POST'])
def delete_lobby(lobby_id):
    """Xóa lobby và tất cả dữ liệu liên quan"""
    if 'user_id' not in session or session['role'] != 'admin':
        flash('Bạn không có quyền thực hiện hành động này!', 'error')
        return redirect(url_for('login'))
    
    conn = sqlite3.connect('uma_draft.db')
    
    try:
        # Xóa tất cả người chơi khỏi lobby
        conn.execute('DELETE FROM lobby_players WHERE lobby_id = ?', [lobby_id])
        
        # Xóa trạng thái ban pick
        conn.execute('DELETE FROM banpick_state WHERE lobby_id = ?', [lobby_id])
        
        # Cập nhật users: đặt lobby_id = NULL cho tất cả người chơi trong lobby
        conn.execute('UPDATE users SET lobby_id = NULL WHERE lobby_id = ?', [lobby_id])
        
        # Xóa lobby
        conn.execute('DELETE FROM lobbies WHERE id = ?', [lobby_id])
        
        conn.commit()
        flash(f'Đã xóa lobby {lobby_id} thành công!', 'success')
        
        # Gửi thông báo realtime
        socketio.emit('lobby_deleted', {
            'lobby_id': lobby_id,
            'message': 'Lobby đã bị xóa bởi admin'
        }, room=f"lobby_{lobby_id}")
        
    except Exception as e:
        conn.rollback()
        flash(f'Lỗi khi xóa lobby: {str(e)}', 'error')
    finally:
        conn.close()
    
    return redirect(url_for('admin_page'))

@app.route('/referee')
def referee_page():
    if 'user_id' not in session or session['role'] != 'referee':
        flash('Bạn không có quyền truy cập!', 'error')
        return redirect(url_for('login'))

    # Lấy danh sách lobbies
    conn = get_conn()

    lobbies = conn.execute(
        '''SELECT l.*, COUNT(lp.user_id) as current_players
                              FROM lobbies l
                              LEFT JOIN lobby_players lp ON l.id = lp.lobby_id
                              GROUP BY l.id
                              ORDER BY l.created_at DESC'''
    ).fetchall()
    conn.close()

    return render_template('referee.html', lobbies=lobbies)


@app.route('/referee/assign-seeds/<int:lobby_id>', methods=['GET', 'POST'])
def assign_seeds(lobby_id):
    """Trọng tài phân seed (thứ tự) cho các trainer trong lobby."""
    if 'user_id' not in session or session.get('role') not in ['referee', 'admin']:
        flash('Bạn không có quyền!', 'error')
        return redirect(url_for('login'))

    conn = get_conn()
    conn.row_factory = sqlite3.Row

    if request.method == 'POST':
        # Lấy dữ liệu seed từ form
        seeds = request.form
        for key, seed in seeds.items():
            if key.startswith('seed_'):
                uid = key.replace('seed_', '')
                if seed:
                    conn.execute(
                        '''INSERT OR REPLACE INTO player_seeds (lobby_id, user_id, seed_number, created_at)
                                    VALUES (?, ?, ?, ?)''',
                        [lobby_id, uid, int(seed), datetime.now()],
                    )
        conn.commit()
        conn.close()
        flash('Đã phân seed thành công!', 'success')
        return redirect(url_for('referee_page'))

    # GET request - hiển thị form phân seed
    players = conn.execute(
        '''SELECT u.* FROM users u
                              JOIN lobby_players lp ON u.id = lp.user_id
                              WHERE lp.lobby_id = ?''',
        [lobby_id],
    ).fetchall()

    # Lấy seed hiện tại nếu có
    existing_seeds = {}
    for player in players:
        seed = conn.execute(
            'SELECT seed_number FROM player_seeds WHERE user_id = ? AND lobby_id = ?',
            [player['id'], lobby_id],
        ).fetchone()
        if seed:
            existing_seeds[player['id']] = seed['seed_number']

    conn.close()

    return render_template(
        'referee/assign_seeds.html',
        lobby_id=lobby_id,
        players=players,
        existing_seeds=existing_seeds,
    )


@app.route('/referee/start-lobby/<int:lobby_id>', methods=['POST'])
def start_lobby(lobby_id):
    if 'user_id' not in session or session['role'] not in ['referee', 'admin']:
        return jsonify({'error': 'Unauthorized'}), 403

    conn = sqlite3.connect('uma_draft.db')
    conn.row_factory = sqlite3.Row

    # Lấy danh sách người chơi
    players = conn.execute(
        'SELECT user_id FROM lobby_players WHERE lobby_id = ?', [lobby_id]
    ).fetchall()

    if len(players) != 4:
        conn.close()
        return jsonify({'error': 'Lobby cần đúng 4 người chơi!'}), 400

    # Kiểm tra đã phân seed chưa
    seeds = conn.execute(
        'SELECT COUNT(*) as cnt FROM player_seeds WHERE lobby_id = ?', [lobby_id]
    ).fetchone()

    if seeds['cnt'] != 4:
        conn.close()
        return jsonify({'error': 'Chưa phân seed cho tất cả người chơi!'}), 400

    # Xóa lượt cũ nếu có
    conn.execute('DELETE FROM player_turns WHERE lobby_id = ?', [lobby_id])

    # Tạo lượt theo seed từ trọng tài
    seeded_players = conn.execute(
        '''SELECT ps.*, u.facebook_link 
                                     FROM player_seeds ps
                                     JOIN users u ON ps.user_id = u.id
                                     WHERE ps.lobby_id = ?
                                     ORDER BY ps.seed_number''',
        [lobby_id],
    ).fetchall()

    for seed_data in seeded_players:
        conn.execute(
            '''INSERT INTO player_turns (lobby_id, turn_order, user_id, remaining_bans, remaining_picks)
                        VALUES (?, ?, ?, ?, ?)''',
            [lobby_id, seed_data['seed_number'], seed_data['user_id'], 1, 3],
        )

    # Tạo state ban pick (vẫn dùng schema hiện tại)
    timer_end = datetime.now() + timedelta(seconds=10)
    conn.execute('DELETE FROM banpick_state WHERE lobby_id = ?', [lobby_id])
    conn.execute(
        '''INSERT INTO banpick_state
                    (lobby_id, timer_end, started_at, status, current_phase, current_team, current_round, bans, picks)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        [lobby_id, timer_end, datetime.now(), 'countdown', 'ban', 1, 1, '[]', '[]'],
    )

    conn.execute('UPDATE lobbies SET status = ? WHERE id = ?', ['countdown', lobby_id])
    conn.commit()

    # Log thứ tự để debug
    print(f"\n=== Lobby {lobby_id} - Thứ tự ban pick ===")
    for s in seeded_players:
        print(f"  Seed {s['seed_number']}: {s['facebook_link']}")

    conn.close()

    # Gửi sự kiện realtime
    socketio.emit(
        'lobby_starting',
        {'lobby_id': lobby_id, 'countdown': 10, 'timer_end': timer_end.isoformat()},
        room=f"lobby_{lobby_id}",
    )

    return jsonify({'success': True, 'message': 'Lobby sẽ bắt đầu sau 10 giây'})

@app.route('/trainer')
def trainer_page():
    if 'user_id' not in session or session['role'] != 'trainer':
        flash('Bạn không có quyền truy cập!', 'error')
        return redirect(url_for('login'))
    
    # Lấy thông tin user và lobby
    conn = get_conn()

    user = conn.execute('SELECT * FROM users WHERE id = ?', [session['user_id']]).fetchone()

    lobby = None
    if user['lobby_id']:
        lobby = conn.execute(
            '''SELECT l.*, COUNT(lp.user_id) as current_players
                                FROM lobbies l
                                LEFT JOIN lobby_players lp ON l.id = lp.lobby_id
                                WHERE l.id = ?''',
            [user['lobby_id']],
        ).fetchone()

    # Lấy danh sách lobby có thể tham gia
    available_lobbies = conn.execute(
        '''SELECT l.*, COUNT(lp.user_id) as current_players
                                        FROM lobbies l
                                        LEFT JOIN lobby_players lp ON l.id = lp.lobby_id
                                        WHERE l.status = 'waiting'
                                        GROUP BY l.id
                                        HAVING current_players < l.max_players'''
    ).fetchall()

    conn.close()
    
    return render_template('trainer.html', user=user, lobby=lobby, available_lobbies=available_lobbies)


@app.route('/lobby/<int:lobby_id>')
def lobby_page(lobby_id):
    if 'user_id' not in session:
        flash('Vui lòng đăng nhập!', 'error')
        return redirect(url_for('login'))

    conn = get_conn()
    lobby = conn.execute('SELECT * FROM lobbies WHERE id = ?', [lobby_id]).fetchone()
    if not lobby:
        conn.close()
        flash('Không tìm thấy lobby!', 'error')
        return redirect(url_for('index'))

    players = conn.execute(
        '''SELECT u.id, u.facebook_link, u.image_path, lp.joined_at
           FROM lobby_players lp
           JOIN users u ON u.id = lp.user_id
           WHERE lp.lobby_id = ?
           ORDER BY lp.joined_at ASC''',
        [lobby_id],
    ).fetchall()

    uma_list = UMA_LIST
    conn.close()

    return render_template(
        'lobby.html',
        lobby=lobby,
        players=players,
        uma_list=uma_list,
        user_role=session.get('role'),
    )


@app.route('/result/<int:lobby_id>')
def result_page(lobby_id):
    """Trang hiển thị kết quả ban pick."""
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = get_conn()
    conn.row_factory = sqlite3.Row

    lobby = conn.execute('SELECT * FROM lobbies WHERE id = ?', [lobby_id]).fetchone()
    if not lobby:
        conn.close()
        flash('Không tìm thấy lobby!', 'error')
        return redirect(url_for('index'))

    # Lấy danh sách actions, kèm số thứ tự pick cho mỗi người chơi
    actions = conn.execute(
        '''
        SELECT pa.*, u.facebook_link, ps.seed_number,
               (
                   SELECT COUNT(*) FROM player_actions pa2
                   WHERE pa2.lobby_id = pa.lobby_id
                     AND pa2.action_type = 'pick'
                     AND pa2.user_id = pa.user_id
                     AND pa2.action_order <= pa.action_order
               ) AS pick_number
        FROM player_actions pa
        JOIN users u ON pa.user_id = u.id
        LEFT JOIN player_seeds ps
               ON ps.user_id = pa.user_id AND ps.lobby_id = pa.lobby_id
        WHERE pa.lobby_id = ?
        ORDER BY pa.action_order
        ''',
        [lobby_id],
    ).fetchall()

    seeds = conn.execute(
        '''
        SELECT ps.*, u.facebook_link
        FROM player_seeds ps
        JOIN users u ON ps.user_id = u.id
        WHERE ps.lobby_id = ?
        ORDER BY ps.seed_number
        ''',
        [lobby_id],
    ).fetchall()

    conn.close()

    bans = [a for a in actions if a['action_type'] == 'ban']
    picks = [a for a in actions if a['action_type'] == 'pick']

    # Nhóm picks theo seed
    picks_by_seed = {}
    for seed in seeds:
        seed_no = seed['seed_number']
        picks_by_seed[seed_no] = {
            'player': seed['facebook_link'],
            'picks': [p for p in picks if p['seed_number'] == seed_no],
        }

    # Map uma_id -> info để tiện lookup trong template
    uma_map = {str(uma['id']): uma for uma in UMA_LIST}

    return render_template(
        'result.html',
        lobby=lobby,
        bans=bans,
        picks_by_seed=picks_by_seed,
        seeds=seeds,
        uma_list=UMA_LIST,
        uma_map=uma_map,
    )


def _serialize_state_row(row: sqlite3.Row):
    if not row:
        return None

    def _to_iso(ts):
        if ts is None:
            return None
        if isinstance(ts, str):
            return ts
        return ts.isoformat()

    return {
        'lobby_id': row['lobby_id'],
        'timer_end': _to_iso(row['timer_end']),
        'started_at': _to_iso(row['started_at']),
        'status': row['status'],
        'phase': row['current_phase'],
        'team': row['current_team'],
        'round': row['current_round'],
        'bans': json.loads(row['bans'] or '[]'),
        'picks': json.loads(row['picks'] or '[]'),
    }


def next_phase(lobby_id: int):
    """Chuyển sang phase tiếp theo cho một lobby."""
    conn = get_conn()

    # Lấy state hiện tại
    state = conn.execute(
        'SELECT * FROM banpick_state WHERE lobby_id = ?', [lobby_id]
    ).fetchone()

    if not state:
        conn.close()
        return

    # Parse bans và picks
    bans = json.loads(state['bans']) if state['bans'] else []
    picks = json.loads(state['picks']) if state['picks'] else []

    # Nếu đang ở countdown, chuyển sang banpick
    if state['status'] == 'countdown':
        new_status = 'banpick'
        new_phase = 'ban'
        new_team = 1
        new_round = 1
        new_timer = datetime.now() + timedelta(seconds=30)

        # Cập nhật lobby status
        conn.execute('UPDATE lobbies SET status = ? WHERE id = ?', ['banpick', lobby_id])

    # Logic chuyển phase bình thường
    else:
        current_phase = state['current_phase']
        current_team = state['current_team']
        current_round = state['current_round']

        # Mỗi team có 2 ban và 2 pick
        total_actions = len(bans) + len(picks)

        if total_actions >= 8:  # Kết thúc: 4 ban + 4 pick
            new_status = 'finished'
            new_phase = 'finished'
            new_team = 1
            new_round = 1
            new_timer = datetime.now()

            # Cập nhật lobby status
            conn.execute(
                'UPDATE lobbies SET status = ? WHERE id = ?', ['finished', lobby_id]
            )
        else:
            # Chuyển phase: ban -> pick -> ban -> pick ...
            if current_phase == 'ban':
                new_phase = 'pick'
                new_team = current_team
                new_round = current_round
            else:  # pick -> ban (chuyển team)
                new_phase = 'ban'
                new_team = 3 - current_team  # Đổi team (1->2, 2->1)
                new_round = current_round + 1 if current_team == 2 else current_round

            new_status = 'banpick'
            new_timer = datetime.now() + timedelta(seconds=30)

    # Cập nhật database
    conn.execute(
        '''UPDATE banpick_state 
                    SET current_phase = ?, current_team = ?, current_round = ?, 
                        timer_end = ?, status = ?, bans = ?, picks = ?
                    WHERE lobby_id = ?''',
        [
            new_phase,
            new_team,
            new_round,
            new_timer,
            new_status,
            json.dumps(bans),
            json.dumps(picks),
            lobby_id,
        ],
    )

    conn.commit()

    # Lấy state mới để broadcast
    new_state = conn.execute(
        'SELECT * FROM banpick_state WHERE lobby_id = ?', [lobby_id]
    ).fetchone()
    conn.close()

    payload = _serialize_state_row(new_state)
    print(f"Lobby {lobby_id} next phase: {payload['phase']}, status: {payload['status']}")

    socketio.emit('phase_change', payload, room=f"lobby_{lobby_id}")

    # Gửi sự kiện next_turn để client cập nhật UI lượt hiện tại
    try:
        conn2 = get_conn()
        conn2.row_factory = sqlite3.Row
        current_player = conn2.execute(
            '''SELECT u.facebook_link, pt.*, ps.seed_number
               FROM player_turns pt
               JOIN users u ON pt.user_id = u.id
               LEFT JOIN player_seeds ps 
                 ON ps.user_id = pt.user_id AND ps.lobby_id = pt.lobby_id
               WHERE pt.lobby_id = ? AND pt.turn_order = ?''',
            [lobby_id, payload['round']],
        ).fetchone()
        conn2.close()

        socketio.emit(
            'next_turn',
            {
                'lobby_id': lobby_id,
                'turn': payload['round'],
                'player': current_player['facebook_link']
                if current_player
                else f'Player {payload["round"]}',
                'seed': current_player['seed_number'] if current_player else None,
                'phase': payload['phase'],
            },
            room=f"lobby_{lobby_id}",
        )
    except Exception as e:
        print(f"Error emitting next_turn for lobby {lobby_id}: {e}")

    # Nếu đã kết thúc ban pick, gửi thêm sự kiện thông báo/redirect
    if payload['status'] == 'finished':
        # Thông báo kết thúc, kèm URL trang kết quả
        socketio.emit(
            'banpick_finished',
            {
                'lobby_id': lobby_id,
                'message': 'Ban pick đã kết thúc!',
                'redirect_url': url_for('result_page', lobby_id=lobby_id),
            },
            room=f"lobby_{lobby_id}",
        )
        # Sự kiện yêu cầu client tự động chuyển sang trang kết quả
        socketio.emit(
            'redirect_to_result',
            {
                'lobby_id': lobby_id,
                'url': url_for('result_page', lobby_id=lobby_id),
                'delay': 2,
            },
            room=f"lobby_{lobby_id}",
        )


def check_timers():
    """Background loop: tự động chuyển phase khi hết giờ."""
    global TIMER_STARTED_AT, TIMER_LAST_TICK_AT, TIMER_LAST_ERROR

    if TIMER_STARTED_AT is None:
        TIMER_STARTED_AT = datetime.now().isoformat()

    while True:
        try:
            TIMER_LAST_TICK_AT = datetime.now().isoformat()

            conn = get_conn()
            states = conn.execute(
                '''SELECT b.*, l.status as lobby_status
                   FROM banpick_state b
                   JOIN lobbies l ON b.lobby_id = l.id
                   WHERE (l.status = 'countdown' OR l.status = 'banpick')
                     AND b.timer_end IS NOT NULL'''
            ).fetchall()
            conn.close()

            now = datetime.now()
            for state in states:
                timer_end = state['timer_end']
                if isinstance(timer_end, str):
                    try:
                        timer_end_dt = datetime.fromisoformat(timer_end)
                    except ValueError:
                        # fallback: sqlite hay lưu "YYYY-MM-DD HH:MM:SS"
                        try:
                            timer_end_dt = datetime.strptime(timer_end, "%Y-%m-%d %H:%M:%S.%f")
                        except ValueError:
                            try:
                                timer_end_dt = datetime.strptime(timer_end, "%Y-%m-%d %H:%M:%S")
                            except ValueError:
                                timer_end_dt = None
                else:
                    timer_end_dt = timer_end

                if timer_end_dt and now >= timer_end_dt:
                    next_phase(state['lobby_id'])
        except Exception as e:
            print(f"Timer error: {e}")
            TIMER_LAST_ERROR = f"{datetime.now().isoformat()} - {e}"

        time.sleep(1)


@app.route('/api/lobby/<int:lobby_id>/state')
def api_lobby_state(lobby_id):
    conn = get_conn()
    state = conn.execute(
        'SELECT * FROM banpick_state WHERE lobby_id = ?', [lobby_id]
    ).fetchone()
    conn.close()

    # Nếu đang countdown và đã hết giờ thì chuyển sang phase tiếp theo
    if state and state['status'] == 'countdown':
        timer_end = state['timer_end']
        if isinstance(timer_end, str):
            try:
                timer_end_dt = datetime.fromisoformat(timer_end)
            except ValueError:
                timer_end_dt = None
        else:
            timer_end_dt = timer_end

        if timer_end_dt and datetime.now() >= timer_end_dt:
            next_phase(lobby_id)
            conn = get_conn()
            state = conn.execute(
                'SELECT * FROM banpick_state WHERE lobby_id = ?', [lobby_id]
            ).fetchone()
            conn.close()

    payload = _serialize_state_row(state) if state else None
    if not payload:
        conn = get_conn()
        lobby = conn.execute(
            'SELECT status FROM lobbies WHERE id = ?', [lobby_id]
        ).fetchone()
        conn.close()
        return jsonify(
            {'lobby_id': lobby_id, 'status': lobby['status'] if lobby else 'waiting'}
        )

    return jsonify(payload)


@app.route('/api/lobby/<int:lobby_id>/action', methods=['POST'])
def api_lobby_action(lobby_id):
    """Xử lý hành động ban/pick của trainer, có kiểm tra team và giới hạn lượt."""
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.get_json(silent=True) or {}
    action = data.get('action')  # 'ban' | 'pick'
    uma_id = str(data.get('uma_id'))
    if action not in ('ban', 'pick') or not uma_id:
        return jsonify({'error': 'Thiếu action/uma_id'}), 400

    user_id = session['user_id']

    conn = get_conn()
    conn.row_factory = sqlite3.Row

    # Lấy state và team của user
    state = conn.execute(
        'SELECT * FROM banpick_state WHERE lobby_id = ?', [lobby_id]
    ).fetchone()
    lobby = conn.execute('SELECT * FROM lobbies WHERE id = ?', [lobby_id]).fetchone()
    user_team = conn.execute(
        'SELECT team_number FROM player_teams WHERE user_id = ? AND lobby_id = ?',
        [user_id, lobby_id],
    ).fetchone()

    if not state or not lobby or lobby['status'] != 'banpick':
        conn.close()
        return jsonify({'error': 'Không trong giai đoạn ban pick'}), 400

    if not user_team:
        conn.close()
        return jsonify({'error': 'Bạn chưa được phân team trong lobby này'}, 400)

    # Kiểm tra đến lượt team nào
    if user_team['team_number'] != state['current_team']:
        conn.close()
        return jsonify({'error': 'Chưa đến lượt team của bạn'}), 400

    # Đếm số hành động của user
    user_actions = conn.execute(
        '''SELECT COUNT(*) as cnt FROM player_actions 
                                   WHERE lobby_id = ? AND user_id = ?''',
        [lobby_id, user_id],
    ).fetchone()

    if action == 'ban' and user_actions['cnt'] >= 1:
        conn.close()
        return jsonify({'error': 'Bạn đã ban 1 con rồi!'}), 400

    if action == 'pick' and user_actions['cnt'] >= 4:  # 1 ban + 3 picks
        conn.close()
        return jsonify({'error': 'Bạn đã chọn đủ 3 con!'}), 400

    # Kiểm tra thời gian
    now = datetime.now()
    timer_end = state['timer_end']
    if isinstance(timer_end, str):
        try:
            timer_end_dt = datetime.fromisoformat(timer_end.replace(' ', 'T'))
        except ValueError:
            timer_end_dt = None
    else:
        timer_end_dt = timer_end

    if timer_end_dt and now > timer_end_dt:
        conn.close()
        return jsonify({'error': 'Đã hết thời gian'}), 400

    # Lấy danh sách bans và picks hiện tại
    bans = json.loads(state['bans'] or '[]')
    picks = json.loads(state['picks'] or '[]')

    # Kiểm tra uma đã được chọn chưa
    if uma_id in bans or uma_id in picks:
        conn.close()
        return jsonify({'error': 'Mã nương đã được chọn'}, 400)

    # Lưu hành động của user
    action_order = len(bans) + len(picks) + 1
    conn.execute(
        '''INSERT INTO player_actions (lobby_id, user_id, action_type, uma_id, action_order, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)''',
        [lobby_id, user_id, action, uma_id, action_order, datetime.now()],
    )

    # Cập nhật bans/picks tổng thể
    if action == 'ban':
        bans.append(uma_id)
    else:
        picks.append(uma_id)

    conn.execute(
        'UPDATE banpick_state SET bans = ?, picks = ? WHERE lobby_id = ?',
        [json.dumps(bans), json.dumps(picks), lobby_id],
    )
    conn.commit()
    conn.close()

    # Sau mỗi hành động hợp lệ, dùng next_phase để chuyển phase/team/timer và broadcast
    next_phase(lobby_id)

    return jsonify({'success': True})


@app.route('/api/lobby/<int:lobby_id>/user-actions')
def api_lobby_user_actions(lobby_id):
    """Trả về số lượt ban/pick đã dùng của user hiện tại trong lobby."""
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 403

    user_id = session['user_id']
    conn = get_conn()
    conn.row_factory = sqlite3.Row

    # Đếm số ban
    bans_row = conn.execute(
        '''SELECT COUNT(*) as cnt FROM player_actions 
           WHERE lobby_id = ? AND user_id = ? AND action_type = 'ban' ''',
        [lobby_id, user_id],
    ).fetchone()

    # Đếm số pick
    picks_row = conn.execute(
        '''SELECT COUNT(*) as cnt FROM player_actions 
           WHERE lobby_id = ? AND user_id = ? AND action_type = 'pick' ''',
        [lobby_id, user_id],
    ).fetchone()

    conn.close()

    return jsonify({'bans': bans_row['cnt'], 'picks': picks_row['cnt']})


@app.route('/api/lobby/<int:lobby_id>/turn-info')
def api_lobby_turn_info(lobby_id):
    """Lấy thông tin về lượt hiện tại và seed cho user trong lobby."""
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 403

    user_id = session['user_id']
    conn = get_conn()
    conn.row_factory = sqlite3.Row

    # Lấy state hiện tại
    state = conn.execute(
        'SELECT * FROM banpick_state WHERE lobby_id = ?', [lobby_id]
    ).fetchone()

    if not state:
        conn.close()
        return jsonify({'error': 'No state'}), 404

    current_turn = state.get('current_turn') if isinstance(state, dict) else state['current_round']

    # Lấy thông tin người chơi hiện tại (theo turn_order nếu có)
    current_player = conn.execute(
        '''SELECT u.facebook_link, pt.*, ps.seed_number
           FROM player_turns pt
           JOIN users u ON pt.user_id = u.id
           LEFT JOIN player_seeds ps 
             ON ps.user_id = pt.user_id AND ps.lobby_id = pt.lobby_id
           WHERE pt.lobby_id = ? AND pt.turn_order = ?''',
        [lobby_id, current_turn],
    ).fetchone()

    # Lấy thông tin lượt của user hiện tại
    my_turns = conn.execute(
        '''SELECT remaining_bans, remaining_picks, turn_order,
                  (SELECT seed_number FROM player_seeds 
                   WHERE user_id = ? AND lobby_id = ?) as seed
           FROM player_turns 
           WHERE lobby_id = ? AND user_id = ?''',
        [user_id, lobby_id, lobby_id, user_id],
    ).fetchone()

    # Lấy danh sách tất cả seed trong lobby
    all_seeds_rows = conn.execute(
        '''SELECT u.facebook_link, ps.seed_number
           FROM player_seeds ps
           JOIN users u ON ps.user_id = u.id
           WHERE ps.lobby_id = ?
           ORDER BY ps.seed_number''',
        [lobby_id],
    ).fetchall()

    conn.close()

    seed_list = [
        {'seed': row['seed_number'], 'player': row['facebook_link']}
        for row in all_seeds_rows
    ]

    return jsonify(
        {
            'current_turn': current_turn,
            'current_player': current_player['facebook_link']
            if current_player
            else f'Player {current_turn}',
            'current_seed': current_player['seed_number'] if current_player else None,
            'is_my_turn': bool(current_player and current_player['user_id'] == user_id),
            'my_turns': {
                'seed': my_turns['seed'] if my_turns else None,
                'turn_order': my_turns['turn_order'] if my_turns else None,
                'remaining_bans': my_turns['remaining_bans'] if my_turns else 0,
                'remaining_picks': my_turns['remaining_picks'] if my_turns else 0,
            }
            if my_turns
            else None,
            'all_seeds': seed_list,
        }
    )


@app.route('/api/lobby/<int:lobby_id>/player-actions')
def api_lobby_player_actions(lobby_id):
    """Lấy danh sách actions của từng player theo seed."""
    conn = get_conn()
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        '''
        SELECT pa.*, ps.seed_number,
               (SELECT COUNT(*) FROM player_actions pa2 
                WHERE pa2.lobby_id = pa.lobby_id 
                  AND pa2.action_type = 'pick' 
                  AND pa2.user_id = pa.user_id 
                  AND pa2.action_order <= pa.action_order) as pick_number
        FROM player_actions pa
        JOIN player_seeds ps ON pa.user_id = ps.user_id AND pa.lobby_id = ps.lobby_id
        WHERE pa.lobby_id = ?
        ORDER BY pa.action_order
        ''',
        [lobby_id],
    ).fetchall()

    result = []
    for a in rows:
        result.append(
            {
                'user_id': a['user_id'],
                'action_type': a['action_type'],
                'uma_id': a['uma_id'],
                'action_order': a['action_order'],
                'seed': a['seed_number'],
                'pick_number': a['pick_number'] if a['action_type'] == 'pick' else None,
            }
        )

    conn.close()
    return jsonify(result)


@app.route('/debug/lobby/<int:lobby_id>')
def debug_lobby(lobby_id):
    """Route debug để kiểm tra trạng thái lobby."""
    conn = get_conn()
    lobby = conn.execute('SELECT * FROM lobbies WHERE id = ?', [lobby_id]).fetchone()
    state = conn.execute('SELECT * FROM banpick_state WHERE lobby_id = ?', [lobby_id]).fetchone()
    conn.close()

    if not lobby:
        return jsonify({'error': 'Lobby not found'}), 404

    result = {
        'lobby': dict(lobby),
        'state': _serialize_state_row(state) if state else None,
    }

    return jsonify(result)


@app.route('/debug/force-start/<int:lobby_id>', methods=['POST'])
def force_start(lobby_id):
    """API debug để force start lobby ngay lập tức."""
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 403

    conn = get_conn()
    past_time = datetime.now() - timedelta(seconds=1)
    conn.execute(
        'UPDATE banpick_state SET timer_end = ? WHERE lobby_id = ?',
        [past_time, lobby_id],
    )
    conn.commit()
    conn.close()

    # Gọi luôn next_phase để phản ứng tức thì, không cần đợi thread 1s
    next_phase(lobby_id)

    return jsonify({'success': True, 'message': 'Đã force start lobby'})


@app.route('/debug/timer-status')
def timer_status():
    """Kiểm tra trạng thái timer thread."""
    import threading

    threads = threading.enumerate()
    timer_threads = [t.name for t in threads if 'Timer' in t.name]

    # Kiểm tra database xem có lobby nào đang countdown/banpick không
    conn = get_conn()
    countdown_lobbies = conn.execute(
        'SELECT id, name, status FROM lobbies WHERE status = "countdown"'
    ).fetchall()
    banpick_lobbies = conn.execute(
        'SELECT id, name, status FROM lobbies WHERE status = "banpick"'
    ).fetchall()
    conn.close()

    return jsonify(
        {
            'total_threads': len(threads),
            'threads': [str(t) for t in threads],
            'timer_threads': timer_threads,
            'timer_thread_running': len(timer_threads) > 0,
            'timer_started_at': TIMER_STARTED_AT,
            'timer_last_tick_at': TIMER_LAST_TICK_AT,
            'timer_last_error': TIMER_LAST_ERROR,
            'countdown_lobbies': len(countdown_lobbies),
            'banpick_lobbies': len(banpick_lobbies),
            'countdown_lobby_ids': [row['id'] for row in countdown_lobbies],
            'banpick_lobby_ids': [row['id'] for row in banpick_lobbies],
        }
    )


@app.route('/trainer/join-lobby/<int:lobby_id>', methods=['POST'])
def join_lobby(lobby_id):
    if 'user_id' not in session or session['role'] != 'trainer':
        flash('Bạn không có quyền!', 'error')
        return redirect(url_for('login'))

    conn = get_conn()

    # Kiểm tra lobby còn chỗ không
    current = conn.execute(
        'SELECT COUNT(*) as count FROM lobby_players WHERE lobby_id = ?',
        [lobby_id],
    ).fetchone()
    lobby = conn.execute('SELECT max_players FROM lobbies WHERE id = ?', [lobby_id]).fetchone()

    if current['count'] >= lobby['max_players']:
        conn.close()
        flash('Lobby đã đầy!', 'error')
        return redirect(url_for('trainer_page'))

    # Thêm vào lobby
    conn.execute(
        'INSERT OR IGNORE INTO lobby_players (lobby_id, user_id, joined_at) VALUES (?, ?, ?)',
        [lobby_id, session['user_id'], datetime.now()],
    )

    # Cập nhật lobby_id cho user
    conn.execute('UPDATE users SET lobby_id = ? WHERE id = ?', [lobby_id, session['user_id']])

    conn.commit()
    conn.close()

    flash('Đã tham gia lobby thành công!', 'success')
    return redirect(url_for('trainer_page'))


@app.route('/trainer/leave-lobby', methods=['POST'])
def leave_lobby():
    if 'user_id' not in session or session['role'] != 'trainer':
        flash('Bạn không có quyền!', 'error')
        return redirect(url_for('login'))

    conn = get_conn()

    # Xóa khỏi lobby_players
    conn.execute('DELETE FROM lobby_players WHERE user_id = ?', [session['user_id']])

    # Cập nhật lobby_id trong users
    conn.execute('UPDATE users SET lobby_id = NULL WHERE id = ?', [session['user_id']])

    conn.commit()
    conn.close()

    flash('Đã rời khỏi lobby!', 'success')
    return redirect(url_for('trainer_page'))

@app.route('/logout')
def logout():
    session.clear()
    flash('Đã đăng xuất!', 'success')
    return redirect(url_for('index'))


@app.route('/debug/uma-list')
def debug_uma_list():
    """Route debug để kiểm tra dữ liệu mã nương"""
    return jsonify({'count': len(UMA_LIST), 'data': UMA_LIST[:10]})


@app.route('/debug/uma-paths')
def debug_uma_paths():
    """Xem đường dẫn ảnh của các mã nương"""
    sample = []
    for uma in UMA_LIST[:10]:  # lấy 10 phần tử đầu
        sample.append(
            {
                'id': uma['id'],
                'name': uma['name'],
                'image': uma.get('image', 'N/A'),
                'thumbnail': uma.get('thumbnail', 'N/A'),
                'icon': uma.get('icon', 'N/A'),
            }
        )
    return jsonify({'total_count': len(UMA_LIST), 'sample': sample})


@app.route('/debug/file/<path:filename>')
def debug_file(filename):
    """Kiểm tra file cụ thể"""
    import os

    current_dir = os.path.dirname(os.path.abspath(__file__))

    # Thử các vị trí khác nhau
    paths_to_try = [
        os.path.join(current_dir, 'assets', filename),
        os.path.join(current_dir, 'assets', 'icons', filename),
        os.path.join(current_dir, 'assets', 'thumbnails', filename),
        os.path.join(current_dir, 'static', 'assets', filename),
        filename,  # đường dẫn tuyệt đối
    ]

    result = {'filename': filename, 'checks': []}

    for path in paths_to_try:
        result['checks'].append({'path': path, 'exists': os.path.exists(path)})

    return jsonify(result)


@app.route('/debug/test-image/<path:filename>')
def test_image(filename):
    """Test hiển thị ảnh trực tiếp"""
    return f'''
    <html>
    <body>
        <h2>Test ảnh: {filename}</h2>
        <img src="/assets/{filename}" style="max-width: 200px;">
        <br>
        <a href="/debug/file/{filename}">Kiểm tra file</a>
    </body>
    </html>
    '''

@app.route('/debug/raw-uma')
def debug_raw_uma():
    """Đọc trực tiếp từ file JSON để kiểm tra"""
    try:
        with open('database/uma_database.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
            return jsonify(
                {
                    'success': True,
                    'total_characters': len(data.get('characters', [])),
                    'sample': data.get('characters', [])[:3],
                }
            )
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    print("=" * 50)
    print("🚀 UMA BANPICK APPLICATION")
    print("=" * 50)

    # Khởi tạo database
    init_db()

    # QUAN TRỌNG: Đảm bảo thread timer được khởi tạo TRƯỚC khi chạy app
    print("\n🔄 Starting timer thread...")
    timer_thread = threading.Thread(target=check_timers, daemon=True, name="TimerThread")
    timer_thread.start()
    print(f"✅ Timer thread started: {timer_thread.name}\n")

    # Chạy app với socketio
    # Tắt reloader để tránh tạo 2 process làm chạy 2 timer thread
    socketio.run(app, debug=True, port=5000, use_reloader=False)
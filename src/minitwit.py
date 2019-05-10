# -*- coding: utf-8 -*-

from hashlib import md5
from datetime import datetime
import time
from sqlite3 import dbapi2 as sqlite3
from contextlib import closing
from flask import Flask, request, session, url_for, redirect, render_template, abort, g, flash
from werkzeug.security import check_password_hash, generate_password_hash

# 상수
DATABASE = r'C:\tmp\minitwit.db'
PER_PAGE = 30
DEBUG = True
SECRET_KEY = 'development key'


# app생성
app = Flask(__name__)
app.config.from_object(__name__)
app.config.from_envvar('MINITWIT_SETTINGS', silent=True)

#유저 존재여부 체크 함수
def get_user_id(username):
    rv = g.db.execute('SELECT USER_ID FROM USER WHERE USERNAME = ?', [username]).fetchone()
    return rv[0] if rv else None

# DB연결 함수
def connect_db():
    return sqlite3.connect(app.config['DATABASE'])

# BD연결 및 사용자정보
@app.before_request
def before_request():
    g.db = connect_db()
    g.user = None
    if 'user_id' in session:
        g.user = query_db('SELECT * FROM USER WHERE USER_ID = ?', [session['user_id']],one = True)

# DB연결 종료
@app.teardown_request
def teardown_request(exception):
    if hasattr(g, 'db'):
        g.db.close()

# DB초기화
def init_db():
    with closing(connect_db()) as db:
        with app.open_resource('schema.sql') as f:
            db.cursor().executescript(f.read())
        db.commit()

# DB질의 처리
def query_db(query, args = (), one = False):
    cur = g.db.execute(query,args)
    rv = [dict((cur.description[idx][0], value)
               for idx, value in enumerate(row)) for row in cur.fetchall()]
    return (rv[0] if rv else None) if one else rv

# gravatar(md5 import) URL생성
def gravatar_url(email, size=80):
    'http://www.gravatar.com/avatar/%s?d=identicon&s=%d' % \
    (md5(email.strip().lower().encode('utf-8')).hexdigest(), size)


# date format
def format_datetime(timestamp):
    return datetime.utcfromtimestamp(timestamp).strftime('%Y-%m-%d @ %H:%M')

# 사용자 등록
@app.route('/register', methods=['GET', 'POST'])
def register():
    if g.user:
        return redirect(url_for('timeline'))
    error = None
    if request.method == 'POST':
        if not request.form['username']:
            error = u'유저명을 입력해주세요'
        elif not request.form['email'] or '@' not in request.form['email']:
            error = u'유효한 이메일주소를 입력해주세요'
        elif not request.form['password']:
            error = u'비밀번호를 입력해주세요'
        elif request.form['password'] != request.form['password2']:
            error = u'비밀번호 확인과 비밀번호가 일치하지 않습니다.'
        elif get_user_id(request.form['username']) is not None:
            error = u'유저명이 이미 존재합니다.'
        else:
            g.db.execute('''INSERT INTO USER(
            USERNAME, EMAIL, PW_HASH) VALUES(?, ?, ?)''',
                         [request.form['username'], request.form['email'],
                          generate_password_hash(request.form['password'])])
            g.db.commit()
            flash(u'성공적으로 회원가입되셨습니다. 로그인이 가능한 상태입니다.')
            return redirect(url_for('login'))


    return render_template('register.html', error=error)

@app.route('/login', methods=['GET','POST'])
def login():
    if g.user:
        return redirect(url_for('timeline'))
    error = None
    if request.method == 'POST':
        user = query_db('''SELECT * FROM USER WHERE 
        USERNAME = ?''', [request.form['username']], one = True)

        if user is None:
            error = u'존재하지 않는 유저명입니다'
        elif not check_password_hash(user['PW_HASH'], request.form['password']):
            error = u'비밀번호가 유효하지 않습니다.'
        else:
            flash(u'로그인 되었습니다')
            session['user_id'] = user['USER_ID']
            return redirect(url_for('timeline'))
    return render_template('login.html',error=error)

@app.route('/logout')
def logout():
    flash(u'로그아웃 하셨습니다.')
    session.pop('user_id', None)
    return redirect(url_for('public_timeline'))

@app.route('/add_message', methods=['POST'])
def add_message():
    if 'user_id' not in session:
        abort(401)
    if request.form['text']:
        g.db.execute('''INSERT INTO MESSAGE(AUTHOR_ID, TEXT, PUB_DATE) VALUES(?, ?, ?)''',
                     (session['user_id'], request.form['text'], int(time.time())))
        g.db.commit()
        flash(u'메시지가 저장되었습니다')
    return redirect(url_for('timeline'))

@app.route('/<username>/follow')
def follow_user(username):
    if not g.user:
        abort(401)
    whom_id = get_user_id(username)
    if whom_id is None:
        abort(404)
    g.db.execute('''INSERT INTO FOLLOWER(WHO_ID, WHOM_ID) VALUES(?, ?)''',
                 [session['user_id'], whom_id])
    g.db.commit()
    flash(u'"%s"님 팔로우 하였습니다.' % username)
    return redirect(url_for('user_timeline', username=username))

@app.route('/<username>/unfollow')
def unfollow_user(username):
    if not g.user:
        abort(401)
    whom_id = get_user_id(username)
    if whom_id is None:
        abort(404)
    g.db.execute('''DELETE FROM FOLLOWER WHERE WHO_ID = ? AND WHOM_ID = ?''',
                 [session['user_id'], whom_id])
    g.db.commit()
    flash(u'"%s"님을 언팔로우 하였습니다.' % username)
    return redirect(url_for('user_timeline', username=username))

@app.route('/public')
def public_timeline():
    return render_template('timeline.html', messages=query_db('''
    SELECT MESSAGE.* , USER.* FROM MESSAGE, USER
    WHERE MESSAGE.AUTHOR_ID = USER.USER_ID
    ORDER BY MESSAGE.PUB_DATE DESC LIMIT ?''', [PER_PAGE]))

@app.route('/')
def timeline():
    if not g.user:
        return redirect(url_for('public_timeline'))
    return render_template('timeline.html', messages=query_db('''
     SELECT MESSAGE.* , USER.* FROM MESSAGE, USER
    WHERE MESSAGE.AUTHOR_ID = USER.USER_ID AND(
    USER.USER_ID = ? OR USER.USER_ID IN (SELECT WHOM_ID FROM FOLLOWER WHERE WHO_ID = ?))
    ORDER BY MESSAGE.PUB_DATE DESC LIMIT ?''',
    [session['user_id'], session['user_id'], PER_PAGE]))

@app.route('/<username>')
def user_timeline(username):
    profile_user = query_db('''
        SELECT * FROM USER WHERE USER_ID = ?
    ''', [username], one=True)

    if profile_user is None:
        abort(404)
    followed = False
    if g.user:
        followed = query_db('''
            SELECT 1 FROM FOLLOWER WHERE FOLLOWER.WHO_ID = ? AND FOLLOWER.WHOM_ID = ?''',
            [session['user_id'], profile_user['USER_ID']], one=True) is not None
    return render_template('timeline.html', messages=query_db('''
        SELECT MESSAGE.*, USER.* FROM MESSAGE, USER 
        WHERE USER.USER_ID = MESSAGE.AUTHOR_ID AND USER.USER_ID = ? 
        ORDER BY MESSAGE.PUB_DATE DESC LIMIT ?''',
        [profile_user['USER_ID'], PER_PAGE]), followed=followed, profile_user=profile_user)

# gravatar 함수를 신사2엔진의 필터로 등록해서 템플릿에서 사용
app.jinja_env.filters['gravatar'] = gravatar_url
app.jinja_env.filters['datetimeformat'] = format_datetime

# DB초기화 및 로컬 테스트 서버 구동
if __name__ == '__main__':
    init_db()
    app.run()






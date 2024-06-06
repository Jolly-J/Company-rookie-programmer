import sys
import requests
import json
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, session, jsonify
import os
import sqlite3
from datetime import datetime
import pytz
import logging
from alibabacloud_dingtalk.robot_1_0.client import Client as dingtalkrobot_1_0Client
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_dingtalk.robot_1_0 import models as dingtalkrobot__1__0_models
from alibabacloud_tea_util import models as util_models
from alibabacloud_tea_util.client import Client as UtilClient

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads/'
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}
app.secret_key = 'supersecretkey'  # 用于闪现消息

# 钉钉群机器人配置（公网转发地址）
PUBLIC_URL_PREFIX = 'http://xxxxxxxxxx'

# DingTalk Credentials
app_key = 'yourappkey'
app_secret = 'yourappsecret'

logging.basicConfig(level=logging.DEBUG)

def get_access_token(app_key, app_secret):
    url = 'https://oapi.dingtalk.com/gettoken'
    params = {
        'appkey': app_key,
        'appsecret': app_secret
    }
    response = requests.get(url, params=params)
    data = response.json()
    logging.debug(f'Token response: {data}')
    if data.get('errcode') == 0:
        return data['access_token']
    else:
        raise Exception(f"Failed to get access token: {data.get('errmsg')}")

def get_user_info(auth_code, access_token):
    url = 'https://oapi.dingtalk.com/user/getuserinfo'
    params = {
        'access_token': access_token,
        'code': auth_code
    }
    response = requests.get(url, params=params)
    return response.json()

def get_user_detail(user_id, access_token):
    url = 'https://oapi.dingtalk.com/topapi/v2/user/get'
    headers = {
        'Content-Type': 'application/json'
    }
    data = {
        'userid': user_id
    }
    response = requests.post(url, data=json.dumps(data), headers=headers, params={'access_token': access_token})
    return response.json()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/dingtalk_login', methods=['POST'])
def dingtalk_login():
    data = request.json
    code = data['code']
    logging.debug(f'Received code: {code}')

    access_token = get_access_token(app_key, app_secret)

    user_info = get_user_info(code, access_token)
    logging.debug(f'User info response: {user_info}')
    if user_info.get('errcode') == 0:
        user_id = user_info['userid']
        user_detail = get_user_detail(user_id, access_token)
        logging.debug(f'User detail response: {user_detail}')

        if user_detail.get('errcode') == 0:
            session['user_name'] = user_detail['result']['name']
            session['user_id'] = user_detail['result']['userid']
            session['job_number'] = user_detail['result']['job_number']
            return jsonify({
                'name': user_detail['result']['name'],
                'avatar': user_detail['result']['avatar'],
                'job_number': user_detail['result']['job_number'],
            })
    return jsonify({'error': 'Failed to get user details', 'details': user_info}), 500

class DingTalkClient:
    @staticmethod
    def create_client() -> dingtalkrobot_1_0Client:
        config = open_api_models.Config()
        config.protocol = 'https'
        config.region_id = 'central'
        return dingtalkrobot_1_0Client(config)

    @staticmethod
    def send_message(access_token, robot_code, user_ids, msg_key, msg_param):
        client = DingTalkClient.create_client()
        batch_send_otoheaders = dingtalkrobot__1__0_models.BatchSendOTOHeaders()
        batch_send_otoheaders.x_acs_dingtalk_access_token = access_token
        batch_send_otorequest = dingtalkrobot__1__0_models.BatchSendOTORequest(
            robot_code=robot_code,
            user_ids=user_ids,
            msg_key=msg_key,
            msg_param=json.dumps(msg_param)
        )
        try:
            response = client.batch_send_otowith_options(batch_send_otorequest, batch_send_otoheaders, util_models.RuntimeOptions())
            logging.debug(f"Response: {response}")
        except Exception as err:
            if not UtilClient.empty(err.code) and not UtilClient.empty(err.message):
                logging.error(f"Error code: {err.code}, Error message: {err.message}")
            else:
                logging.error(f"Unexpected error: {err}")

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def init_db():
    conn = sqlite3.connect('feedback.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS feedback (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        service_type TEXT,
                        feedback_type TEXT DEFAULT '',
                        description TEXT,
                        filename TEXT,
                        timestamp TEXT,
                        feedback_names TEXT DEFAULT '',
                        feedback_idnumber TEXT DEFAULT ''
                      )''')
    conn.commit()
    conn.close()

def get_beijing_time():
    tz = pytz.timezone('Asia/Shanghai')
    beijing_time = datetime.now(tz)
    return beijing_time.strftime('%Y年%m月%d日%H点%M分')

@app.route('/feedback/canteen')
def feedback_canteen():
    return render_template('feedback_canteen.html')

@app.route('/feedback/apartment')
def feedback_apartment():
    return render_template('feedback_apartment.html')

@app.route('/feedback/security')
def feedback_security():
    return render_template('feedback_security.html')

@app.route('/feedback/cleaning')
def feedback_cleaning():
    return render_template('feedback_cleaning.html')

@app.route('/feedback/maintenance')
def feedback_maintenance():
    return render_template('feedback_maintenance.html')

@app.route('/feedback/daily')
def feedback_daily():
    return render_template('feedback_daily.html')

@app.route('/feedback_records')
def feedback_records():
    if 'logged_in' in session and session['logged_in']:
        conn = sqlite3.connect('feedback.db')
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM feedback ORDER BY timestamp DESC')
        feedbacks = cursor.fetchall()
        conn.close()
        return render_template('feedback_records.html', feedbacks=feedbacks)
    else:
        flash('请先登录管理员账户。')
        return redirect(url_for('login'))

@app.route('/feedback_detail/<int:feedback_id>')
def feedback_detail(feedback_id):
    if 'logged_in' in session and session['logged_in']:
        conn = sqlite3.connect('feedback.db')
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM feedback WHERE id = ?', (feedback_id,))
        feedback = cursor.fetchone()
        conn.close()
        return render_template('feedback_detail.html', feedback=feedback)
    else:
        flash('请先登录管理员账户。')
        return redirect(url_for('login'))

@app.route('/submit_feedback', methods=['POST'])
def submit_feedback():
    if 'user_name' not in session or 'job_number' not in session:
        return redirect(url_for('feedback_failure'))

    service_type = request.form['service_type']
    description = request.form['description']
    feedback_names = session.get('user_name', '')
    feedback_idnumber = session.get('job_number', '')
    feedback_type = request.form.get('feedback_type', '')

    file = request.files.get('file')
    filename = ''
    timestamp = get_beijing_time()

    if file and allowed_file(file.filename):
        if not os.path.exists(app.config['UPLOAD_FOLDER']):
            os.makedirs(app.config['UPLOAD_FOLDER'])
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        file.save(file_path)
        filename = file.filename  # 只保存文件名

    # 保存反馈到数据库
    conn = sqlite3.connect('feedback.db')
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO feedback (service_type, feedback_type, description, filename, timestamp, feedback_names, feedback_idnumber) VALUES (?, ?, ?, ?, ?, ?, ?)',
        (service_type, feedback_type, description, filename, timestamp, feedback_names, feedback_idnumber))
    feedback_id = cursor.lastrowid
    conn.commit()
    conn.close()

    detail_url = f"{PUBLIC_URL_PREFIX}{url_for('feedback_detail', feedback_id=feedback_id)}"

    # 钉钉推送消息
    access_token = get_access_token(app_key, app_secret)
    markdown_text = f"### {service_type}\n\n**姓名**: {feedback_names}\n\n**工号**: {feedback_idnumber}\n\n**描述**: {description}\n"
    image_url = f"https://imgse.com/i/pkYZolT"
    markdown_text += f"![图片]({image_url})\n"
    markdown_text += f"\n[查看详情]({detail_url})"

    msg_param = {
        "title": "意见反馈",
        "text": markdown_text
    }
    DingTalkClient.send_message(
        access_token=access_token,
        robot_code='dingf2yu501kazzbffuy',
        user_ids=['xxxxx','xxxxx' ,'xxxxx'],  # 这里使用你想要通知的用户ID
        msg_key='sampleMarkdown',
        msg_param=msg_param
    )

    return redirect(url_for('feedback_success'))

@app.route('/feedback_success')
def feedback_success():
    return render_template('feedback_success.html')

@app.route('/feedback_failure')
def feedback_failure():
    return render_template('feedback_failure.html')

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username == 'admin' and password == 'admin':
            session['logged_in'] = True
            return redirect(url_for('feedback_records'))
        else:
            flash('用户名或密码错误，请重试。')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    flash('您已成功登出。')
    return redirect(url_for('index'))

if __name__ == '__main__':
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])
    init_db()
    app.run(host='127.0.0.1', port=3000, debug=True)
    #可自己修改端口号

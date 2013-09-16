import io

from flask import Flask, send_file

app = Flask(__name__)

@app.route('/')
def index():
    buf = io.BytesIO()
    buf.write('hello world')
    buf.seek(0)
    return send_file(buf,
                     attachment_filename="testing.txt",
                     as_attachment=True)

import json
from flask import Flask


app = Flask(__name__)


@app.route("/")
def post_endpoint():
    ret = {
        "results": []
    }
    return json.dumps(ret, ensure_ascii=False)


if __name__ == '__main__':
    app.run(host="0.0.0.0", port=9000, debug=True)
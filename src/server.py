from flask import Flask

app = Flask(__name__)


@app.route("/")
def sanity_check():
    """Sanity check

    :return: Successful response
    :type: dict
    """
    return {"success": True, "msg": "Docker container running."}


if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)

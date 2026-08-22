from flask import Flask
import os
app = Flask(__name__)
@app.route("/")
def home(): return "MINIMAL OK - weekly-planner works!"
@app.route("/health")
def health(): return {"status":"ok", "mode":"minimal"}
if __name__ == "__main__":
    port=int(os.getenv("PORT","5000"))
    app.run(host="0.0.0.0", port=port)

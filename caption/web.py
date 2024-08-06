from flask import Flask, render_template, jsonify, request

class WebApp:
    def __init__(self, args):
        self.app = Flask(__name__)
        self.transcribed_text = []
        self.PORT = 5000
        self.args = args
        self.setup_routes()

    def setup_routes(self):
        @self.app.route('/')
        def index():
            return render_template('index.html')

        @self.app.route('/transcript', methods=['GET'])
        def get_transcript():
            return jsonify({'text': self.transcribed_text})

    def start_server(self):
        print(f"Listening on http://localhost:{self.PORT}")
        self.app.run(debug=True, host='0.0.0.0', port=self.PORT)

    def start(self):
        self.start_server()

if __name__ == '__main__':
    web_app = WebApp({})
    web_app.start()
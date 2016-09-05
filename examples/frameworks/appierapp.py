import appier

class HelloApp(appier.App):

    @appier.route("/", "GET")
    def hello(self):
        return "Hello, world!"

HelloApp().serve()
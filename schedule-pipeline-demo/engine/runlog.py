"""A logger: collects lines and (optionally) prints them as they happen."""


class RunLog:
    def __init__(self, echo=True):
        self.lines = []
        self.echo = echo

    def add(self, text=""):
        self.lines.append(text)
        if self.echo:
            print(text)

    def extend(self, lines):
        for line in lines:
            self.add(line)

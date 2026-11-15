"""A minimal logger: collects lines and (optionally) prints them as they happen."""


class RunLog:
    def __init__(self, echo=True):
        self.lines = []
        self.echo = echo

    def add(self, text=""):
        self.lines.append(text)
        if self.echo:
            print(text)

    def dump(self):
        """Print everything that was collected silently."""
        for line in self.lines:
            print(line)

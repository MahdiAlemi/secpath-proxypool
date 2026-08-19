from dataclasses import dataclass


@dataclass(slots=True)
class CLIState:
    json_output: bool = False
    no_color: bool = False
    verbose: bool = False

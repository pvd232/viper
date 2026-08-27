"""Run one frozen project plan."""

from sample_project.stages.train import train

from viper import run


def main() -> None:
    """Execute the complete plan selected by the command-line arguments."""
    run(train)


if __name__ == "__main__":
    main()

from pardal.checks import Severity, Stage, check


@check(
    id="gd32.fixture",
    stage=Stage.SOURCE_CONTRACT,
    default_severity=Severity.INFO,
)
def fixture_check(ctx):
    return []

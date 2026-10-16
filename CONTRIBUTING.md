# Contributing

Thanks for helping. Before a larger change, open an issue and check SCOPE.md.

## Setup
```
git clone https://github.com/matthewprice/otto && cd otto
python3 -m unittest discover -s tests -v
claude plugin validate . --strict
```

## Rules
- Python standard library only. Python 3.9 compatible.
- Observers fail open and never print to the model. Only the guard may exit 2.
- The ledger stays an allowlist. A new field needs a reason in the PR and a test.
- Label every figure MEASURED or ESTIMATE. Do not add savings claims without a measured before and after.
- Fixtures are synthetic and must stay labelled as such.
- Skills stay thin: logic goes in scripts, with tests.
- No em dashes in repo prose.

## Pull requests
Small, one concern, tests included. Describe what you verified and what you did not.

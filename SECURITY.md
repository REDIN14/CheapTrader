# Security

CheapTrader runs on your own PC and can send orders to a broker through MetaTrader 5, so a security
problem can cost real money. Please report it privately.

## Reporting a vulnerability

Use GitHub's **Report a vulnerability** button on the *Security* tab of the repository (private security
advisories). Please do not open a public issue for a security problem. Say what you found, how to reproduce
it, and what an attacker could do with it. You will get an answer as soon as possible.

## What is in scope

* Anything that makes the program send an order, change a stop or close a position **without the user
  asking** (including a web page in the browser talking to the program on `127.0.0.1`).
* Anything that leaks the MetaTrader login, the account, or the contents of the data folder.
* Escaping the indicator sandbox (user-written Python indicators run in a restricted process with a time
  and memory limit).

## How the program protects you

* It listens on `127.0.0.1` only: other computers cannot reach it.
* Sending orders is **off** in a fresh install. It has to be switched on in the app (MetaTrader menu) or in
  the settings file (`CT_ALLOW_LIVE_ORDERS=true`).
* There is no telemetry, no account and no update check: it does not contact the internet by itself.
* Indicators run in a sandbox; they cannot import arbitrary modules, open files or reach the network.

## Supported versions

Only the latest release is supported.

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
* There is no telemetry and no account. The one thing it contacts the internet for by itself is the update
  check: a request to `api.github.com` for the latest release of this repository, when the program starts and
  every six hours (switch it off in the About window, or with `CT_UPDATE_CHECK=false`).
* An update is installed only when you click **Install and restart**. The installer is downloaded over HTTPS
  from GitHub's own hosts only (a redirect to any other host is refused), its SHA-256 is compared with the one
  in `SHA256SUMS.txt` of the same release, and only then is it run, silently, by a small script that waits for the
  program to close. The installer is not code-signed, and the checksum comes from the same release as the file:
  it protects against a damaged download, not against a release changed on GitHub itself. A copy that was not set
  up by the installer never installs anything by itself.
* Indicators run in a sandbox; they cannot import arbitrary modules, open files or reach the network.

## Supported versions

Only the latest release is supported.

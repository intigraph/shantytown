# Installation reference

The [README](https://github.com/intigraph/shantytown#install) has the one-line
install. This page covers pinned releases, the alternatives and removal.

## What you need

- Linux or macOS, with Python 3.11 or newer.
- `tmux`, to run a crew. The installer and the previews work without it.
- For the shell installer: Python's `venv` and `pip`, and `curl`.
- At least one agent program, installed and signed in, before you launch a
  crew. See [Harnesses](harnesses.md).

Shantytown has one runtime dependency, the `cryptography` package. Every
install method below brings it in.

## Shell installer

```sh
curl -fsSL https://raw.githubusercontent.com/intigraph/shantytown/main/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
st --version
```

The installer downloads the release wheel and its `SHA256SUMS`, checks the
wheel against the checksum and installs it into its own virtual environment.
Each release is stored in `share/shantytown/<tag>` under the prefix, and
`bin/st` under the prefix is a link to that release.

Two environment variables change what it does. Set them on the shell that
receives the pipe:

| variable | default | effect |
|---|---|---|
| `STACK_VERSION` | the latest stable release | install this tag, for example `v0.22.0` |
| `STACK_INSTALL_ROOT` | `~/.local` | install under this prefix; put its `bin` directory on `PATH` |

```sh
curl -fsSL https://raw.githubusercontent.com/intigraph/shantytown/main/install.sh |
  STACK_VERSION=v0.22.0 STACK_INSTALL_ROOT="$HOME/.local" sh
```

## pipx

Download the wheel and its checksums from the
[release page](https://github.com/intigraph/shantytown/releases/latest), check
the wheel, then install it. Replace `0.22.0` with the release you want:

```sh
curl -fLO https://github.com/intigraph/shantytown/releases/download/v0.22.0/shantytown-0.22.0-py3-none-any.whl
curl -fLO https://github.com/intigraph/shantytown/releases/download/v0.22.0/SHA256SUMS
grep 'shantytown-0.22.0-py3-none-any.whl$' SHA256SUMS | shasum -a 256 -c
pipx install ./shantytown-0.22.0-py3-none-any.whl
export PATH="${PIPX_BIN_DIR:-$HOME/.local/bin}:$PATH"
st --version
```

The `PATH` line makes `st` available in this shell. For later shells, run
`pipx ensurepath` and open a new terminal. [Release checksums](releases.md)
describes how the checksum file is produced.

## From source

```sh
git clone https://github.com/intigraph/shantytown
pipx install ./shantytown
```

To work on Shantytown itself, use an editable install instead:
`python3 -m pip install -e .` inside the clone. A crew that installs this way
runs whatever its checkout has pulled, so `main` reaches it without a release.

## Removal

For a pipx installation, run `pipx uninstall shantytown`.

For the shell installer, name the prefix and the release you installed. Remove
the command link only if it still points to that release, then remove that
release's directory:

```sh
prefix="$HOME/.local"
version=v0.22.0
if [ "$(readlink "$prefix/bin/st")" = "$prefix/share/shantytown/$version/bin/st" ]; then
  rm "$prefix/bin/st"
fi
rm -r "$prefix/share/shantytown/$version"
```

Other installed releases stay in place. So do your crew's store and its
configuration, which live outside the install prefix.

## After installing

- [Getting started](getting-started.md) creates and launches a first crew.
- [Configuration](configuration.md) lists every setting.
- `st ops doctor` reports what is installed, what is stale and what is missing.

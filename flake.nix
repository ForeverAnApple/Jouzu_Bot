{
  description = "python env for jouzu_bot";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs {
          inherit system;
        };
        python = pkgs.python313;
      in
      {
        devShells.default = pkgs.mkShell {
          buildInputs = [
            python
            pkgs.uv

            # System deps for matplotlib / seaborn / bar_chart_race
            pkgs.cairo
            pkgs.pkg-config
            pkgs.gobject-introspection
            pkgs.libffi
            pkgs.sqlite
          ];

          shellHook = ''
            # Rebuild venv if missing or if its python symlink is dead
            # (e.g. nix-store GC, python bump, or project was moved).
            if [ ! -x .venv/bin/python ]; then
              echo "Creating venv..."
              rm -rf .venv
              uv venv .venv --python ${python}/bin/python
              rm -f .venv/.installed
            fi
            source .venv/bin/activate

            if [ ! -f .venv/.installed ] || [ requirements.txt -nt .venv/.installed ]; then
              echo "Installing Python deps..."
              uv pip install -r requirements.txt
              touch .venv/.installed
            fi

            echo "Jouzu Bot dev environment"
            echo "========================="
            echo "Python: $(python --version)"
          '';
        };
      }
    );
}

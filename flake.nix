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
          ];

          shellHook = ''
            if [ ! -d .venv ]; then
              echo "Creating venv..."
              uv venv .venv
            fi
            source .venv/bin/activate

            if [ ! -f .venv/.installed ]; then
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

{
  description = "CxDICT — LLM-generate CC-CEDICT in other languages, allowing for authoritative sources to take priority.";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
      # Single source of truth for the package identity: read off pyproject.
      projectMeta = (builtins.fromTOML (builtins.readFile ./pyproject.toml)).project;
      # Only packaging inputs enter the store: never data/ or output/.
      packageSrc = pkgs: pkgs.lib.fileset.toSource {
        root = ./.;
        fileset = pkgs.lib.fileset.unions [
          ./src
          ./pyproject.toml
          ./README.md
        ];
      };
    in
    {
      packages = forAllSystems (pkgs: {
        default = pkgs.python312Packages.buildPythonPackage {
          pname = projectMeta.name;
          inherit (projectMeta) version;
          pyproject = true;
          src = packageSrc pkgs;
          build-system = [ pkgs.python312Packages.hatchling ];
          dependencies = [ pkgs.python312Packages.jsonschema ];
          doCheck = false; # suite runs separately in CI (needs data fixtures)
          # Importing parser.json executes the schema load: this fails the
          # build if schemas/ data files ever go missing from the wheel.
          pythonImportsCheck = [ "cfdict_next" "cfdict_next.parser.json" ];
        };
      });

      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          packages = with pkgs; [
            # Wrapped interpreter: plain `python312` plus separate
            # `python312Packages.*` entries do NOT put the libs on
            # sys.path — withPackages builds one python with them wired in.
            (python312.withPackages (ps: with ps; [
              pytest
              pyyaml
              jsonschema
            ]))
            git
            gzip
            dos2unix
          ];

          shellHook = ''
            export PYTHONPATH="$PWD/src:$PYTHONPATH"
            echo "CxDICT dev shell — $(python3 --version)"
          '';
        };
      });
    };
}

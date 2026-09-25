{
  description = "CFDICT-Next — Chinese-French dictionary: CFDICT + CC-CEDICT scope + LLM-generated French";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
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
            # Append, never clobber: the withPackages wrapper exports its
            # own PYTHONPATH, and `import cfdict_next` additionally needs src.
            export PYTHONPATH="$PWD/src:$PYTHONPATH"
            echo "CFDICT-Next dev shell — $(python3 --version)"
          '';
        };
      });
    };
}

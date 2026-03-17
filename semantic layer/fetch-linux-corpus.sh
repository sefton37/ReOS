#!/bin/bash
# =============================================================================
# ReOS Semantic Layer Corpus Fetcher
# =============================================================================
# Downloads all source material for building the Linux command semantic layer.
# Run this on Corellia. Everything lands in ~/reos-corpus/
#
# Total size estimate: ~200-400MB
# Time estimate: 5-15 minutes depending on connection
# =============================================================================

set -euo pipefail

CORPUS_DIR="$HOME/reos-corpus"
mkdir -p "$CORPUS_DIR"
cd "$CORPUS_DIR"

echo "============================================="
echo "ReOS Corpus Fetcher"
echo "Target: $CORPUS_DIR"
echo "============================================="

# -------------------------------------------------------
# 1. tldr-pages — intent-to-command mappings
#    ~3000+ commands, structured markdown
#    Key dirs: pages/linux/ and pages/common/
# -------------------------------------------------------
echo ""
echo "[1/6] tldr-pages (intent-to-command mappings)..."
if [ -d "tldr" ]; then
    echo "  Already exists, pulling latest..."
    cd tldr && git pull && cd ..
else
    git clone --depth 1 https://github.com/tldr-pages/tldr.git
fi
echo "  Done. Key paths:"
echo "    tldr/pages/linux/   — Linux-specific commands"
echo "    tldr/pages/common/  — Cross-platform commands"

# -------------------------------------------------------
# 2. Linux man-pages project — comprehensive reference
#    Maintained by Michael Kerrisk, covers syscalls,
#    library functions, core commands, file formats
#    Sections: man1 (commands), man5 (file formats),
#              man7 (overviews), man8 (admin commands)
# -------------------------------------------------------
echo ""
echo "[2/6] Linux man-pages project (comprehensive reference)..."
if [ -d "man-pages" ]; then
    echo "  Already exists, pulling latest..."
    cd man-pages && git pull && cd ..
else
    git clone --depth 1 https://git.kernel.org/pub/scm/docs/man-pages/man-pages.git
fi
echo "  Done. Key paths:"
echo "    man-pages/man1/  — User commands"
echo "    man-pages/man5/  — File formats & configs"
echo "    man-pages/man7/  — Overviews & conventions"
echo "    man-pages/man8/  — System admin commands"

# -------------------------------------------------------
# 3. Community cheatsheets — task-oriented snippets
#    Practical, real-world command patterns
# -------------------------------------------------------
echo ""
echo "[3/6] Community cheatsheets (task-oriented patterns)..."
if [ -d "cheatsheets" ]; then
    echo "  Already exists, pulling latest..."
    cd cheatsheets && git pull && cd ..
else
    git clone --depth 1 https://github.com/cheat/cheatsheets.git
fi
echo "  Done. Path: cheatsheets/"

# -------------------------------------------------------
# 4. Arch Wiki — the best "how Linux actually works" docs
#    Download the arch-wiki-docs package, extract English HTML
#    These are pre-rendered, clean HTML files (~4500 pages)
# -------------------------------------------------------
echo ""
echo "[4/6] Arch Wiki (system-level documentation)..."
ARCHWIKI_DIR="arch-wiki"
if [ -d "$ARCHWIKI_DIR" ]; then
    echo "  Already exists, skipping. Delete $ARCHWIKI_DIR to re-download."
else
    mkdir -p "$ARCHWIKI_DIR"
    echo "  Downloading arch-wiki-docs package..."
    curl -L "https://archlinux.org/packages/extra/any/arch-wiki-docs/download/" \
        -o arch-wiki-docs.pkg.tar.zst

    echo "  Extracting..."
    # Need zstd to decompress
    if ! command -v zstd &>/dev/null; then
        echo "  Installing zstd..."
        if command -v apt &>/dev/null; then
            sudo apt install -y zstd
        elif command -v dnf &>/dev/null; then
            sudo dnf install -y zstd
        elif command -v pacman &>/dev/null; then
            sudo pacman -S --noconfirm zstd
        fi
    fi

    # Extract the package
    tar --use-compress-program=unzstd -xf arch-wiki-docs.pkg.tar.zst -C "$ARCHWIKI_DIR"

    # Move English HTML files to top level for easy access
    if [ -d "$ARCHWIKI_DIR/usr/share/doc/arch-wiki/html/en" ]; then
        mv "$ARCHWIKI_DIR/usr/share/doc/arch-wiki/html/en" "$ARCHWIKI_DIR/en"
        rm -rf "$ARCHWIKI_DIR/usr"  # clean up package structure
    fi

    # Clean up the tarball
    rm -f arch-wiki-docs.pkg.tar.zst

    # Remove non-English content to save space (optional)
    rm -f "$ARCHWIKI_DIR"/.BUILDINFO "$ARCHWIKI_DIR"/.MTREE "$ARCHWIKI_DIR"/.PKGINFO 2>/dev/null || true
fi
echo "  Done. Path: arch-wiki/en/"

# -------------------------------------------------------
# 5. GNU Coreutils manual — authoritative docs for
#    ls, cp, mv, chmod, chown, sort, cut, etc.
#    Single-page HTML for easy ingestion
# -------------------------------------------------------
echo ""
echo "[5/6] GNU Coreutils manual..."
mkdir -p gnu-docs
if [ -f "gnu-docs/coreutils.html" ]; then
    echo "  Already exists, skipping."
else
    curl -L "https://www.gnu.org/software/coreutils/manual/coreutils.html" \
        -o gnu-docs/coreutils.html
fi

# Also grab the Bash reference manual
if [ -f "gnu-docs/bash.html" ]; then
    echo "  Bash manual already exists, skipping."
else
    echo "  Downloading Bash reference manual..."
    curl -L "https://www.gnu.org/software/bash/manual/bash.html" \
        -o gnu-docs/bash.html
fi

# And the findutils manual (find, xargs, locate)
if [ -f "gnu-docs/findutils.html" ]; then
    echo "  Findutils manual already exists, skipping."
else
    echo "  Downloading findutils manual..."
    curl -L "https://www.gnu.org/software/findutils/manual/html_mono/find.html" \
        -o gnu-docs/findutils.html
fi

# And grep
if [ -f "gnu-docs/grep.html" ]; then
    echo "  Grep manual already exists, skipping."
else
    echo "  Downloading grep manual..."
    curl -L "https://www.gnu.org/software/grep/manual/grep.html" \
        -o gnu-docs/grep.html
fi

# And sed
if [ -f "gnu-docs/sed.html" ]; then
    echo "  Sed manual already exists, skipping."
else
    echo "  Downloading sed manual..."
    curl -L "https://www.gnu.org/software/sed/manual/sed.html" \
        -o gnu-docs/sed.html
fi

# And gawk
if [ -f "gnu-docs/gawk.html" ]; then
    echo "  Gawk manual already exists, skipping."
else
    echo "  Downloading gawk manual..."
    curl -L "https://www.gnu.org/software/gawk/manual/gawk.html" \
        -o gnu-docs/gawk.html
fi

echo "  Done. Path: gnu-docs/"

# -------------------------------------------------------
# 6. Installed man pages from THIS system
#    Export all locally installed man pages as plain text.
#    This captures distro-specific commands and tools
#    that the generic man-pages project doesn't cover.
# -------------------------------------------------------
echo ""
echo "[6/6] Exporting local system man pages..."
LOCAL_MAN_DIR="local-man-pages"
mkdir -p "$LOCAL_MAN_DIR"

# Only re-export if directory is empty or has fewer than 100 files
FILE_COUNT=$(find "$LOCAL_MAN_DIR" -type f | wc -l)
if [ "$FILE_COUNT" -lt 100 ]; then
    echo "  Exporting all installed man pages as plain text..."
    echo "  (This may take a few minutes)"

    # Export man pages from sections 1, 5, 7, 8 (most relevant)
    for section in 1 5 7 8; do
        mkdir -p "$LOCAL_MAN_DIR/man${section}"
        # Get list of all man pages in this section
        man -k . 2>/dev/null | grep "(${section})" | awk '{print $1}' | sort -u | while read -r cmd; do
            # Clean the command name (remove trailing stuff)
            clean_cmd=$(echo "$cmd" | sed 's/[^a-zA-Z0-9._-]//g')
            if [ -n "$clean_cmd" ]; then
                outfile="$LOCAL_MAN_DIR/man${section}/${clean_cmd}.txt"
                if [ ! -f "$outfile" ]; then
                    man "$section" "$clean_cmd" 2>/dev/null | col -bx > "$outfile" 2>/dev/null || true
                fi
            fi
        done
        count=$(find "$LOCAL_MAN_DIR/man${section}" -type f | wc -l)
        echo "  Section $section: $count pages exported"
    done
else
    echo "  Already exported ($FILE_COUNT files found), skipping."
fi
echo "  Done. Path: local-man-pages/"

# -------------------------------------------------------
# Summary
# -------------------------------------------------------
echo ""
echo "============================================="
echo "CORPUS COMPLETE"
echo "============================================="
echo ""
echo "Directory structure:"
echo ""
echo "  ~/reos-corpus/"
echo "  ├── tldr/                    # Intent-to-command (markdown)"
echo "  │   ├── pages/linux/         #   Linux-specific commands"
echo "  │   └── pages/common/        #   Cross-platform commands"
echo "  ├── man-pages/               # Official Linux man-pages project"
echo "  │   ├── man1/                #   User commands"
echo "  │   ├── man5/                #   File formats"
echo "  │   ├── man7/                #   Overviews"
echo "  │   └── man8/                #   Admin commands"
echo "  ├── cheatsheets/             # Community cheatsheets"
echo "  ├── arch-wiki/en/            # Arch Wiki HTML (English)"
echo "  ├── gnu-docs/                # GNU manuals (HTML)"
echo "  │   ├── coreutils.html"
echo "  │   ├── bash.html"
echo "  │   ├── findutils.html"
echo "  │   ├── grep.html"
echo "  │   ├── sed.html"
echo "  │   └── gawk.html"
echo "  └── local-man-pages/         # This system's installed man pages"
echo "      ├── man1/"
echo "      ├── man5/"
echo "      ├── man7/"
echo "      └── man8/"
echo ""

# Disk usage
echo "Disk usage:"
du -sh "$CORPUS_DIR"/* 2>/dev/null | sed 's|'"$CORPUS_DIR"'/||'
echo ""
TOTAL=$(du -sh "$CORPUS_DIR" | cut -f1)
echo "Total: $TOTAL"
echo ""
echo "============================================="
echo "Next step: Point Claude Code at ~/reos-corpus/"
echo "and have it build the semantic layer."
echo "============================================="

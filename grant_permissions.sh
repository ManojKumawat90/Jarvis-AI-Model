#!/bin/bash
# Opens each required macOS Privacy pane so you can grant Terminal full access.
# Run once: bash grant_permissions.sh

echo ""
echo "┌─────────────────────────────────────────────────────────┐"
echo "│          JARVIS – macOS Permission Setup                │"
echo "│                                                         │"
echo "│  In each pane that opens, find 'Terminal' (or your     │"
echo "│  terminal app) and toggle it ON.  Close when done.     │"
echo "└─────────────────────────────────────────────────────────┘"
echo ""

open_pane() {
    local name="$1"
    local url="$2"
    echo "→ Opening: $name"
    open "$url"
    read -p "  Press Enter when done ..."
    echo ""
}

open_pane "Microphone" \
    "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"

open_pane "Accessibility" \
    "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"

open_pane "Full Disk Access" \
    "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"

open_pane "Automation (control other apps)" \
    "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation"

open_pane "Speech Recognition (optional – for offline STT)" \
    "x-apple.systempreferences:com.apple.preference.security?Privacy_SpeechRecognition"

echo "✓ All permissions configured."
echo "  Run JARVIS with:  python3 main.py"
echo ""

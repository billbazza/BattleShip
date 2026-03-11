#!/bin/bash
# Run this once to store all Battleship pipeline secrets in 1Password.
# You'll be prompted to paste each value.

echo "=== Battleship Pipeline — 1Password Setup ==="
echo ""

# Anthropic / Claude API key
# Get it from: https://console.anthropic.com → API Keys
echo "1. Paste your Anthropic (Claude) API key:"
read -s ANTHROPIC_KEY
op item create \
  --category "API Credential" \
  --title "Anthropic" \
  --vault "Private" \
  "credential=$ANTHROPIC_KEY"
echo "   ✅ Anthropic key saved"

echo ""
echo "2. SMTP host (e.g. smtp.mail.me.com for iCloud, smtp.gmail.com for Gmail):"
read SMTP_HOST

echo "3. SMTP username / sending email address:"
read SMTP_USER

echo "4. SMTP password (app-specific password — NOT your account password):"
echo "   iCloud: appleid.apple.com → Sign-In & Security → App-Specific Passwords"
echo "   Gmail:  myaccount.google.com → Security → 2-Step → App passwords"
read -s SMTP_PASS

op item create \
  --category "Login" \
  --title "SMTP" \
  --vault "Private" \
  "host=$SMTP_HOST" \
  "username=$SMTP_USER" \
  "password=$SMTP_PASS"
echo "   ✅ SMTP credentials saved"

echo ""
echo "5. Stripe secret key (sk_live_... or sk_test_... — press Enter to skip):"
read -s STRIPE_KEY
if [ -n "$STRIPE_KEY" ]; then
  op item create \
    --category "API Credential" \
    --title "Stripe" \
    --vault "Private" \
    "api-key=$STRIPE_KEY"
  echo "   ✅ Stripe key saved"
else
  echo "   (skipped — Stripe not configured)"
fi

echo ""
echo "=== Setup complete. Run the pipeline to verify: ==="
echo "python3 /Users/will/Obsidian-Vaults/BattleShip-Vault/scripts/battleship_pipeline.py"

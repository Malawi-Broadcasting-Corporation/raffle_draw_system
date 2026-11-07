"""Checkable draws (issue #6): anyone with the locked ticket list and the seed can re-run a draw.

1. Lock:  the ticket pool is frozen and fingerprinted (SHA-256 of a canonical text form).
2. Seed:  randomness MBC can't control or predict, obtained *after* the lock:
          - drand: the first public drand round produced after the lock time, or
          - manual: e.g. dice rolled live on air, with who rolled them.
3. Pick:  winner n is chosen with HMAC-SHA256(key, "n:attempt") where
          key = SHA-256("<fingerprint>:<seed>"), using rejection sampling so every
          remaining ticket has exactly the same chance. Numbers that already won
          (including voided winners) are removed before each pick.

This module has no Flask or database code so the algorithm can be read, tested and
re-implemented independently.
"""
import hashlib
import hmac
import time
from datetime import datetime, timezone

import requests

ALGORITHM_VERSION = 'mbc-raffle-v1'
DRAND_URL = 'https://api.drand.sh'
DRAND_TIMEOUT = 10


class SeedError(Exception):
    """The seed could not be obtained or is not acceptable."""


# ---------------------------------------------------------------- fingerprint

def canonical_pool(tickets):
    """tickets: [(entry_id, phone)] in pool order -> the exact text that gets fingerprinted."""
    lines = [ALGORITHM_VERSION] + [f"{i}:{entry_id}:{phone}" for i, (entry_id, phone) in enumerate(tickets)]
    return '\n'.join(lines) + '\n'


def fingerprint(tickets):
    return hashlib.sha256(canonical_pool(tickets).encode('utf-8')).hexdigest()


# ---------------------------------------------------------------- selection

def draw_key(pool_fingerprint, seed):
    return hashlib.sha256(f"{pool_fingerprint}:{seed}".encode('utf-8')).digest()


def pick_index(key, position, size):
    """Uniform index in [0, size) for winner `position`, without modulo bias."""
    if size <= 0:
        raise ValueError("Nothing left to pick from")
    space = 1 << 256
    limit = space - (space % size)  # largest multiple of size that fits in 256 bits
    attempt = 0
    while True:
        digest = hmac.new(key, f"{position}:{attempt}".encode('ascii'), hashlib.sha256).digest()
        value = int.from_bytes(digest, 'big')
        if value < limit:
            return value % size
        attempt += 1  # practically never happens; keeps the result exactly uniform


def pick(key, position, tickets, won_phones):
    """Choose the ticket for `position` from the pool, skipping numbers that already won."""
    candidates = [t for t in tickets if t[1] not in won_phones]
    return candidates[pick_index(key, position, len(candidates))]


def replay(tickets, seed, recorded):
    """Re-run a draw. recorded: [(position, entry_id, phone)] sorted by position.

    Returns [(position, expected_entry_id, recorded_entry_id, ok)].
    """
    key = draw_key(fingerprint(tickets), seed)
    won, results = set(), []
    for position, entry_id, phone in recorded:
        expected_id, expected_phone = pick(key, position, tickets, won)
        results.append((position, expected_id, entry_id, expected_id == entry_id))
        won.add(phone)
    return results


# ---------------------------------------------------------------- seeds

def validate_manual_seed(value, reference):
    value = (value or '').strip()
    reference = (reference or '').strip()
    if len(value) < 6:
        raise SeedError("The seed must be at least 6 characters (e.g. 6 dice rolls: 351624)")
    if not reference:
        raise SeedError("Say where the seed came from, e.g. 'Dice rolled on air by the presenter'")
    return value, reference


def _get_json(url):
    r = requests.get(url, timeout=DRAND_TIMEOUT)
    if r.status_code != 200:
        return None
    return r.json()


def drand_round_after(locked_at, info):
    """Number and time of the first drand round produced strictly after `locked_at` (naive UTC)."""
    lock_ts = locked_at.replace(tzinfo=timezone.utc).timestamp()
    genesis, period = info['genesis_time'], info['period']
    round_no = int((lock_ts - genesis) // period) + 2
    return round_no, genesis + (round_no - 1) * period


def fetch_drand_seed(locked_at, base_url=DRAND_URL, max_wait=75, get_json=_get_json, sleep=time.sleep,
                     now=time.time):
    """Wait for the first drand round after the lock and return (randomness, reference)."""
    try:
        info = get_json(f"{base_url}/info")
    except requests.RequestException as e:
        raise SeedError(f"Could not reach drand ({e}). Use a manual seed instead.") from e
    if not info:
        raise SeedError("drand did not answer. Use a manual seed instead.")

    round_no, round_time = drand_round_after(locked_at, info)
    deadline = now() + max_wait
    while now() < deadline:
        wait = round_time - now()
        if wait > 0:
            sleep(min(wait + 0.5, max(deadline - now(), 0)))
            continue
        try:
            data = get_json(f"{base_url}/public/{round_no}")
        except requests.RequestException:
            data = None
        if data and data.get('round') == round_no and data.get('randomness'):
            when = datetime.fromtimestamp(round_time, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
            return data['randomness'], f"drand round {round_no} ({when}), chain {info.get('hash', '?')}"
        sleep(2)
    raise SeedError(f"drand round {round_no} did not arrive in time. Try again or use a manual seed.")

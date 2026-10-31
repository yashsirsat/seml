"""
AIML Lab - Assignment 2: Constraint Satisfaction Problem (CSP)
Application : Bus departure scheduling at MSRTC bus station, Pune
Student     : Yash A Sirsat, PRN 123B1F093, TY IT (Div B), Batch B4
Each of 10 trips gets (time slot, platform). Sample data made for this assignment.
Run: python csp_bus_scheduling.py   (standard library only)
"""
TRIPS = {"T1": ("Pune-Mumbai (Shivneri)", "AC"), "T2": ("Pune-Mumbai (Ordinary)", "Non-AC"),
         "T3": ("Pune-Nashik (Shivneri)", "AC"), "T4": ("Pune-Kolhapur", "Non-AC"),
         "T5": ("Pune-Satara", "Non-AC"), "T6": ("Pune-Solapur", "Non-AC"),
         "T7": ("Pune-Aurangabad (Shivneri)", "AC"), "T8": ("Pune-Shirdi", "Non-AC"),
         "T9": ("Pune-Mahabaleshwar", "Non-AC"), "T10": ("Pune-Sangli", "Non-AC")}
SLOTS = ["06:00", "08:00", "10:00", "12:00", "14:00", "16:00"]
PLATFORMS = ["P1", "P2", "P3"]          # P1 = AC bay (takes AC and Non-AC); P2, P3 = Non-AC only
MAX_PER_SLOT = 2
CORRIDOR = [("T1", "T2"), ("T4", "T5"), ("T4", "T10"), ("T5", "T10"), ("T3", "T8"), ("T7", "T8")]
SHARED = [("T1", "T3"), ("T2", "T8"), ("T4", "T6"), ("T5", "T9"), ("T7", "T10")]
UNAVAILABLE = {"T3": [0, 1], "T7": [3, 4, 5], "T9": [0, 1], "T6": [4, 5], "T1": [0, 1], "T2": [0]}

# Domain of each trip = (slot, platform) pairs that pass the single-trip rules
DOMAIN = {t: [(s, p) for s in range(len(SLOTS)) if s not in UNAVAILABLE.get(t, [])
              for p in PLATFORMS if TRIPS[t][1] == "Non-AC" or p == "P1"] for t in TRIPS}

def is_safe(t, slot, plat, sched):
    """Can trip t take (slot, plat) given the trips already scheduled?"""
    if sum(1 for s, _ in sched.values() if s == slot) >= MAX_PER_SLOT:
        return False                                          # slot is full
    for o, (s2, p2) in sched.items():
        if (s2, p2) == (slot, plat): return False             # platform already used
        pair = {t, o}
        if s2 == slot and any(pair == set(c) for c in CORRIDOR): return False   # corridor clash
        if abs(s2 - slot) < 2 and any(pair == set(c) for c in SHARED): return False  # driver gap
    return True

def legal(t, sched):
    return [(s, p) for s, p in DOMAIN[t] if is_safe(t, s, p, sched)]

def solve(sched, stats, mrv=False, fc=False, order=None):
    """Backtracking search. mrv = pick trip with fewest legal values; fc = forward checking."""
    if len(sched) == len(TRIPS): return True
    free = [t for t in (order or TRIPS) if t not in sched]
    t = min(free, key=lambda x: len(legal(x, sched))) if mrv else free[0]
    for val in legal(t, sched):
        sched[t] = val; stats[0] += 1
        dead_end = fc and any(not legal(u, sched) for u in TRIPS if u not in sched)
        if not dead_end and solve(sched, stats, mrv, fc, order): return True
        del sched[t]; stats[1] += 1                           # undo = backtrack
    return False

def verify(sched):
    """Independent check of every rule on the final timetable."""
    slot = lambda t: sched[t][0]
    return {"All 10 trips scheduled": len(sched) == len(TRIPS),
            "AC buses only on P1": all(TRIPS[t][1] == "Non-AC" or sched[t][1] == "P1" for t in sched),
            "Driver availability": all(slot(t) not in UNAVAILABLE.get(t, []) for t in sched),
            "One bus per platform per slot": len(set(sched.values())) == len(sched),
            "No corridor clash": all(slot(a) != slot(b) for a, b in CORRIDOR),
            "Shared driver >= 2 slots apart": all(abs(slot(a) - slot(b)) >= 2 for a, b in SHARED),
            "Max 2 departures per slot": all(sum(s == k for s, _ in sched.values()) <= MAX_PER_SLOT
                                             for k in range(len(SLOTS)))}

if __name__ == "__main__":
    methods = {"Plain backtracking": {}, "Plain (reverse order)": {"order": list(TRIPS)[::-1]},
               "Backtracking + MRV": {"mrv": True}, "MRV + forward checking": {"mrv": True, "fc": True}}
    results = {}
    for name, opts in methods.items():
        sched, stats = {}, [0, 0]
        ok = solve(sched, stats, **opts)
        results[name] = (ok, stats, sched)

    sched = results["Plain backtracking"][2]
    print("DEPARTURE TIMETABLE")
    for k, label in enumerate(SLOTS):
        rows = sorted((p, t) for t, (s, p) in sched.items() if s == k)
        print(f"{label}: " + ("(no departures)" if not rows else ""))
        for p, t in rows: print(f"   Platform {p}: {t}  {TRIPS[t][0]} [{TRIPS[t][1]}]")

    print("\nPLATFORM USAGE")
    for p in PLATFORMS:
        n = sum(q == p for _, q in sched.values())
        print(f"   {p}: {n}/{len(SLOTS)} slots used ({n / len(SLOTS) * 100:.0f}%)")

    print("\nCONSTRAINT VERIFICATION")
    for rule, ok in verify(sched).items(): print(f"   {rule:34}: {ok}")

    print(f"\n{'Method':26}{'Assignments':>12}{'Backtracks':>12}{'Valid':>8}")
    for name, (ok, (a, b), sc) in results.items():
        print(f"{name:26}{a:>12}{b:>12}{str(ok and all(verify(sc).values())):>8}")

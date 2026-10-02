"""Section 6 calibration: the 8 hire profiles' criterion scores and expected routes.

Scores, G1 and routes are copied from kargo_pm_spm_rubric.txt Section 6.
The other facts (PM-title years, ops tenure, ownership years, Mumbai) are NOT
in the rubric's table; they are set to values consistent with Sections 1-2
and the listed routes. Replace them with figures read from the real CVs.
"""

# name: (G1, pm_title_years, ops_tenure_years, ownership_role_years, mumbai_stated)
FACTS = {
    "Lavanya Iyer":         (True,  3.0, 3.0, 3.0, True),   # F1 fires for SPM (Section 6)
    "Rohan Desai":          (True,  0.0, 3.0, 5.0, True),
    "Sunita Krishnamurthy": (False, 0.0, 6.0, 4.0, True),
    "Meghna Tiwari":        (False, 0.0, 2.0, 4.0, True),
    "Aditya Shetty":        (False, 0.0, 2.0, 4.0, True),
    "Preetham Rao":         (True,  0.0, 0.0, 4.0, True),
    "Rahul Bose":           (False, 0.0, 0.0, 4.0, True),
    # Section 6 says "3 yrs PM" (PM table) and "4.5 yrs" (SPM table); both
    # clear the PM floor (2) and miss the SPM floor (5). 4.5 used here.
    "Vikram Nair":          (True,  4.5, 0.0, 4.5, True),
}

PM = {
    # name: ([C1..C6], total, route)
    "Lavanya Iyer":         ([4, 4, 4, 3, 3, 4], 93.75, "ADVANCE"),
    "Rohan Desai":          ([4, 3, 4, 4, 3, 2], 87.50, "ADVANCE"),
    "Sunita Krishnamurthy": ([4, 1, 4, 4, 4, 3], 82.50, "HUMAN REVIEW"),
    "Meghna Tiwari":        ([3, 2, 4, 4, 2, 3], 76.25, "HUMAN REVIEW"),
    "Aditya Shetty":        ([3, 1, 3, 3, 3, 3], 65.00, "HUMAN REVIEW"),
    "Preetham Rao":         ([1, 2, 3, 3, 0, 1], 45.00, "REJECT"),
    "Rahul Bose":           ([0, 2, 3, 1, 3, 2], 41.25, "REJECT"),
    "Vikram Nair":          ([0, 3, 2, 1, 1, 3], 38.75, "HUMAN REVIEW"),
}

SPM = {
    # name: ([S1..S6], total, route)
    "Rohan Desai":          ([4, 3, 4, 4, 4, 4], 95.00, "ADVANCE"),
    "Sunita Krishnamurthy": ([2, 4, 4, 4, 4, 4], 87.50, "HUMAN REVIEW"),
    "Lavanya Iyer":         ([3, 4, 4, 4, 2, 3], 83.75, "ADVANCE"),
    "Meghna Tiwari":        ([1, 3, 3, 4, 3, 4], 68.75, "HUMAN REVIEW"),
    "Preetham Rao":         ([4, 2, 1, 3, 2, 4], 67.50, "HUMAN REVIEW"),
    "Aditya Shetty":        ([0, 3, 3, 3, 3, 3], 56.25, "HUMAN REVIEW"),
    "Vikram Nair":          ([2, 2, 0, 2, 3, 1], 43.75, "REJECT"),
    "Rahul Bose":           ([0, 3, 0, 3, 3, 1], 40.00, "REJECT"),
}

EXPECTED = {"PM": PM, "SPM": SPM}

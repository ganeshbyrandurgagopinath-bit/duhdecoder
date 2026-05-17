const state = {
  problems: [],
  selectedProblemId: null,
  solvedProblemIds: loadSolvedProblemIds(),
};

const problemListEl = document.getElementById("problemList");
const problemModeEl = document.getElementById("problemMode");
const problemTitleEl = document.getElementById("problemTitle");
const problemDifficultyEl = document.getElementById("problemDifficulty");
const problemDescriptionEl = document.getElementById("problemDescription");
const functionNameLabelEl = document.getElementById("functionNameLabel");
const pageShellEl = document.getElementById("pageShell");
const problemSidebarEl = document.getElementById("problemSidebar");
const sidebarToggleEl = document.getElementById("sidebarToggle");
const sampleCasesEl = document.getElementById("sampleCases");
const codeEditorEl = document.getElementById("codeEditor");
const runButtonEl = document.getElementById("runButton");
const logoutButtonEl = document.getElementById("logoutButton");
const runStatusEl = document.getElementById("runStatus");
const runMessageEl = document.getElementById("runMessage");
const resultsListEl = document.getElementById("resultsList");
const SOLVED_STORAGE_KEY = "duhdecoder.solvedProblems";

function loadSolvedProblemIds() {
  try {
    const rawValue = window.localStorage.getItem(SOLVED_STORAGE_KEY);
    if (!rawValue) {
      return new Set();
    }

    const parsedValue = JSON.parse(rawValue);
    if (!Array.isArray(parsedValue)) {
      return new Set();
    }

    return new Set(parsedValue.filter((value) => typeof value === "string"));
  } catch {
    return new Set();
  }
}

function persistSolvedProblemIds() {
  try {
    window.localStorage.setItem(
      SOLVED_STORAGE_KEY,
      JSON.stringify([...state.solvedProblemIds]),
    );
  } catch {
    // Ignore storage failures so the runner still works in restricted browsers.
  }
}

function markProblemSolved(problemId) {
  if (!problemId || state.solvedProblemIds.has(problemId)) {
    return;
  }

  state.solvedProblemIds.add(problemId);
  persistSolvedProblemIds();
}

function formatValue(value) {
  return JSON.stringify(value);
}

function getSelectedProblem() {
  return state.problems.find((problem) => problem.id === state.selectedProblemId);
}

function updateSidebarState() {
  const collapsed = problemSidebarEl.classList.contains("collapsed");
  pageShellEl.classList.toggle("sidebar-collapsed", collapsed);
  sidebarToggleEl.setAttribute("aria-expanded", String(!collapsed));
}

function renderProblemList() {
  problemListEl.innerHTML = "";

  state.problems.forEach((problem) => {
    const button = document.createElement("button");
    button.className = `problem-item ${problem.id === state.selectedProblemId ? "active" : ""}`;
    const isSolved = state.solvedProblemIds.has(problem.id);
    button.innerHTML = `
      <span class="problem-item-header">
        <span class="problem-item-title">${problem.title}</span>
        <span class="problem-item-check ${isSolved ? "solved" : ""}" aria-hidden="true">${isSolved ? "✓" : ""}</span>
      </span>
      <span class="problem-item-meta">${problem.mode} · ${problem.difficulty}</span>
    `;
    button.addEventListener("click", () => {
      state.selectedProblemId = problem.id;
      renderSelectedProblem(true);
      renderProblemList();
    });
    problemListEl.appendChild(button);
  });
}

function renderSelectedProblem(resetCode = false) {
  const problem = getSelectedProblem();
  if (!problem) {
    return;
  }

  problemModeEl.textContent = problem.mode || "Bug Fix";
  problemTitleEl.textContent = problem.title;
  problemDifficultyEl.textContent = problem.difficulty;
  problemDescriptionEl.textContent = problem.description;
  functionNameLabelEl.textContent = problem.function_name;

  sampleCasesEl.innerHTML = "";
  problem.samples.forEach((sample, index) => {
    const card = document.createElement("div");
    card.className = "sample-card";
    card.innerHTML = `
      <strong>Example ${index + 1}</strong>
      <p>Input: <code>${formatValue(sample.input)}</code></p>
      <p>Output: <code>${formatValue(sample.output)}</code></p>
    `;
    sampleCasesEl.appendChild(card);
  });

  if (resetCode || !codeEditorEl.value.trim()) {
    codeEditorEl.value = problem.starter_code;
  }

  resetResults();
}

function resetResults() {
  runStatusEl.textContent = "Waiting for a run";
  runStatusEl.className = "run-status idle";
  runMessageEl.textContent = 'Click "Run Code" to execute your solution.';
  resultsListEl.innerHTML = "";
}

function renderResults(result) {
  runStatusEl.textContent = result.status.replaceAll("_", " ");
  runStatusEl.className = `run-status ${result.status}`;
  runMessageEl.textContent = result.message;
  resultsListEl.innerHTML = "";

  (result.results || []).forEach((item) => {
    const card = document.createElement("div");
    card.className = `result-card ${item.passed ? "pass" : "fail"}`;
    card.innerHTML = `
      <strong>Test ${item.test_number}: ${item.passed ? "Passed" : "Failed"}</strong>
      <p>Input: <code>${formatValue(item.input)}</code></p>
      <p>Expected: <code>${formatValue(item.expected)}</code></p>
      <p>Actual: <code>${formatValue(item.actual)}</code></p>
    `;
    resultsListEl.appendChild(card);
  });

  if (result.status === "accepted") {
    const currentProblem = getSelectedProblem();
    markProblemSolved(currentProblem?.id);
    renderProblemList();
  }
}

async function loadProblems() {
  const response = await fetch("/api/problems");
  if (response.status === 401) {
    window.location.href = "/login";
    return;
  }
  state.problems = await response.json();
  state.selectedProblemId = state.problems[0]?.id ?? null;
  renderProblemList();
  renderSelectedProblem(true);
}

async function runCode() {
  const problem = getSelectedProblem();
  if (!problem) {
    return;
  }

  runButtonEl.disabled = true;
  runStatusEl.textContent = "Running...";
  runStatusEl.className = "run-status idle";
  runMessageEl.textContent = "Executing Python 3 against the test cases...";
  resultsListEl.innerHTML = "";

  try {
    const response = await fetch("/api/run", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        problem_id: problem.id,
        code: codeEditorEl.value,
      }),
    });

    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.error || "Request failed.");
    }

    renderResults(result);
  } catch (error) {
    runStatusEl.textContent = "request failed";
    runStatusEl.className = "run-status runtime_error";
    runMessageEl.textContent = error.message;
    resultsListEl.innerHTML = "";
  } finally {
    runButtonEl.disabled = false;
  }
}

async function logout() {
  await fetch("/api/auth/logout", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({}),
  });
  window.location.href = "/login";
}

function toggleSidebar() {
  problemSidebarEl.classList.toggle("collapsed");
  updateSidebarState();
}

runButtonEl.addEventListener("click", runCode);
logoutButtonEl.addEventListener("click", logout);
sidebarToggleEl.addEventListener("click", toggleSidebar);
updateSidebarState();
loadProblems().catch((error) => {
  runStatusEl.textContent = "load failed";
  runStatusEl.className = "run-status runtime_error";
  runMessageEl.textContent = error.message;
});

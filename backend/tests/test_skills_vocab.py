"""Skills vocabulary: aliases, tricky names, ambiguous words (no false positives)."""
from backend.services.skills_vocab import find_skills, normalize_skill, vocabulary


def test_vocab_loaded():
    v = vocabulary()
    assert 400 <= len(v) <= 900
    assert "python" in v and "postgresql" in v and "go" in v


def test_normalize_aliases():
    assert normalize_skill("Postgres") == "postgresql"
    assert normalize_skill(" psql ") == "postgresql"
    assert normalize_skill("JS") == "javascript"
    assert normalize_skill("k8s") == "kubernetes"
    assert normalize_skill("ML") == "machine learning"
    assert normalize_skill("LLMs") == "large language models"
    assert normalize_skill("Golang") == "go"
    assert normalize_skill("Scikit Learn") == "scikit-learn"
    assert normalize_skill("Some Niche Tool") == "some niche tool"


def test_special_characters():
    text = "Strong C++ and C# skills, .NET Core, Node.js, Next.js, CI/CD pipelines and scikit-learn."
    found = find_skills(text)
    for s in ["c++", "c#", ".net", "node.js", "next.js", "ci/cd", "scikit-learn"]:
        assert s in found, s
    assert "javascript" not in found


def test_order_and_dedupe():
    text = "Python, PostgreSQL, Docker. Also Postgres and python3 again; Kubernetes (k8s)."
    assert find_skills(text) == ["python", "postgresql", "docker", "kubernetes"]


def test_java_is_not_javascript():
    assert find_skills("JavaScript developer") == ["javascript"]
    assert find_skills("Java developer") == ["java"]


def test_llm_terms():
    text = "Build RAG pipelines with LangChain and a vector database; prompt engineering; LLMs."
    found = find_skills(text)
    for s in ["retrieval-augmented generation", "langchain", "vector databases",
              "prompt engineering", "large language models"]:
        assert s in found, s


def test_go_only_in_safe_contexts():
    assert "go" in find_skills("Experience with Python, Go, and Rust")
    assert "go" in find_skills("Backend services written in Go.")
    assert "go" in find_skills("Golang microservices")
    assert "go" in find_skills("- Go\n- Python")
    assert "go" not in find_skills("Your go-to person for infra. Go above and beyond!")
    assert "go" not in find_skills("We go fast and ship often. Go to market quickly")


def test_r_only_in_safe_contexts():
    assert "r" in find_skills("Statistics in Python or R.")
    assert "r" in find_skills("Tools: SQL, R, Tableau")
    assert "r" in find_skills("R programming for analysis")
    assert "r" not in find_skills("Our R&D team. Grade R. Section R of the handbook")
    assert "r" not in find_skills("rapid growth, really great")


def test_c_only_in_safe_contexts():
    assert find_skills("Proficiency in C/C++")[:2] == ["c", "c++"]
    assert "c" in find_skills("C programming on microcontrollers")
    assert "c" not in find_skills("Plan C. Vitamin C. Objective-C apps")
    assert "objective-c" in find_skills("Objective-C apps")


def test_case_sensitive_words():
    assert "react" in find_skills("Frontend in React and TypeScript")
    assert "react" not in find_skills("You react quickly to incidents")
    assert "swift" not in find_skills("swift delivery of features")
    assert "rest api" not in find_skills("the rest of the team")
    assert "rest api" in find_skills("design REST APIs")


def test_hyphen_space_variants():
    assert "machine learning" in find_skills("machine-learning models")
    assert "react native" in find_skills("React-Native apps")


def test_extra_terms():
    found = find_skills("We use Home Assistant and FastAPI", extra_terms=["Home Assistant", "fastapi"])
    assert found == ["home assistant", "fastapi"]
    # extra terms are per call
    assert "home assistant" not in find_skills("We use Home Assistant")


def test_empty():
    assert find_skills("") == []

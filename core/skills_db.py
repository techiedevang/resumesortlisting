"""
skills_db.py
-------------
Skill taxonomy used for (a) skill extraction / gap analysis and
(b) role-fit classification and skill-priority ranking.

SKILLS_TAXONOMY maps a canonical skill to its surface-form aliases, so
"React.js", "ReactJS" and "React JS" all resolve to "react".

An alias that starts with "regex:" is used as a raw regular expression.
This is needed for skills such as the C language, where the plain letter
"c" is far too ambiguous ("grade C", "vitamin C") and is only accepted
when it appears inside a skills list next to other languages.

ROLE_PROFILES maps each target role to the skills that signal it, with a
weight from 0.5 (weak signal) to 3 (defining skill). The same skill can
signal several roles: Python counts for ML, data and software roles, but
with a different weight for each.
"""

SKILLS_TAXONOMY = {
    # --- Programming languages ---
    "python": ["python", "python3"],
    "java": ["java"],
    "javascript": ["javascript", "js", "es6", "ecmascript"],
    "typescript": ["typescript"],
    "c++": ["c++", "cpp"],
    "c": [
        "c programming", "c language", "c/c++",
        r"regex:(?<![a-z0-9.+#])c(?=\s*[,/|;]\s*(?:c\+\+|java|python|c#|javascript|sql)(?![a-z0-9]))",
        r"regex:(?<=[,/|;])\s*c(?=\s*(?:[,|;]|$))",
    ],
    "c#": ["c#", "c-sharp", "csharp"],
    "go": ["golang", "go lang"],  # bare "go" excluded: too common an English word
    "kotlin": ["kotlin"],
    "php": ["php", "laravel"],
    "sql": ["sql", "mysql", "postgresql", "postgres", "t-sql", "pl/sql"],
    "r": ["r programming", "r language"],

    # --- Core CS ---
    "data structures": ["data structures", "dsa", "algorithms", "competitive programming"],
    "oop": ["oop", "oops", "object oriented", "object-oriented", "design patterns"],
    "linux": ["linux", "ubuntu", "shell scripting", "bash"],

    # --- Web / full stack ---
    "react": ["react.js", "reactjs", "react js", "react"],
    "angular": ["angular.js", "angularjs", "angular"],
    "vue": ["vue.js", "vuejs", "vue"],
    "node.js": ["node.js", "nodejs", "node js", "express.js", "expressjs"],
    "django": ["django"],
    "flask": ["flask"],
    "spring boot": ["spring boot", "springboot", "spring framework", "hibernate"],
    "html/css": ["html", "css", "html5", "css3", "bootstrap", "tailwind"],
    "rest api": ["rest api", "restful", "rest apis", "api development"],

    # --- Data / ML / AI ---
    "machine learning": ["machine learning", "ml"],
    "deep learning": ["deep learning", "neural network", "neural networks", "cnn", "lstm"],
    "nlp": ["nlp", "natural language processing", "bert"],
    "computer vision": ["computer vision", "opencv", "image classification", "object detection"],
    "pandas": ["pandas"],
    "numpy": ["numpy"],
    "scikit-learn": ["scikit-learn", "sklearn", "scikit learn"],
    "tensorflow": ["tensorflow", "keras", "tf.keras"],
    "pytorch": ["pytorch", "torch"],
    # Split so one resume line such as "RAG with LangChain and HuggingFace"
    # is three separate skills, not 3 mentions of a single "llm" skill.
    "llm": ["llm", "large language model", "genai", "generative ai", "gpt", "openai api"],
    "rag": ["rag", "retrieval-augmented generation", "retrieval augmented generation",
            "langchain", "vector database"],
    "huggingface": ["huggingface", "hugging face", "transformers"],
    "statistics": ["statistics", "statistical", "hypothesis testing", "regression"],
    "data analysis": ["data analysis", "data analytics", "data visualization",
                      "data visualisation", "dashboard", "dashboards"],
    "power bi": ["power bi", "powerbi"],
    "tableau": ["tableau"],
    "excel": ["excel", "ms excel", "advanced excel"],

    # --- Cloud / DevOps ---
    "aws": ["aws", "amazon web services", "ec2"],
    "azure": ["azure", "microsoft azure"],
    "gcp": ["gcp", "google cloud"],
    "docker": ["docker", "containerization", "containerisation"],
    "kubernetes": ["kubernetes", "k8s", "helm"],
    "terraform": ["terraform", "ansible", "infrastructure as code"],
    "ci/cd": ["ci/cd", "continuous integration", "jenkins", "github actions", "gitlab ci"],
    "git": ["git", "github", "gitlab", "version control"],

    # --- Databases ---
    "mongodb": ["mongodb", "mongo db", "nosql"],
    "oracle db": ["oracle db", "oracle database"],

    # --- Soft / project skills ---
    "project management": ["project management", "agile", "scrum", "jira"],
    "communication": ["communication skills", "stakeholder management"],
    "leadership": ["leadership", "team lead", "mentoring"],
    "problem solving": ["problem solving", "analytical skills", "critical thinking"],
}


# Role -> {skill: weight}. Higher weight = stronger signal for that role.
ROLE_PROFILES = {
    "Software Developer": {
        "java": 3, "c++": 3, "c": 3, "c#": 3, "data structures": 3, "oop": 3,
        "spring boot": 2, "go": 2, "kotlin": 2, "python": 1.5, "sql": 1,
        "rest api": 1, "linux": 1, "git": 1, "oracle db": 1, "javascript": 0.5,
    },
    "Web Developer": {
        "html/css": 3, "javascript": 3, "react": 3, "angular": 3, "vue": 3,
        "node.js": 3, "php": 3, "typescript": 2, "django": 1.5, "flask": 1.5,
        "rest api": 1.5, "mongodb": 1, "git": 0.5, "sql": 0.5,
    },
    "AI / ML Engineer": {
        "machine learning": 3, "deep learning": 3, "nlp": 3, "computer vision": 3,
        "tensorflow": 3, "pytorch": 3, "scikit-learn": 3, "llm": 3,
        "rag": 3, "huggingface": 2,
        "python": 1.5, "numpy": 1.5, "pandas": 1.5, "statistics": 1.5,
    },
    "Data Analyst": {
        "data analysis": 3, "power bi": 3, "tableau": 3, "excel": 2.5, "sql": 2.5,
        "statistics": 2, "pandas": 1.5, "python": 1, "r": 2, "numpy": 0.5,
    },
    # Backend developers routinely deploy to AWS/Docker, so those carry less
    # weight for DevOps than Kubernetes or Terraform, which are rarely
    # needed outside an infrastructure role.
    "Backend Developer": {
        "django": 3, "flask": 3, "spring boot": 3, "node.js": 2.5, "rest api": 3,
        "sql": 2, "oracle db": 2, "mongodb": 2, "python": 2, "java": 1.5,
        "php": 1, "docker": 1, "git": 0.5,
    },
    "DevOps / Cloud Engineer": {
        "kubernetes": 3, "terraform": 3, "aws": 2, "azure": 2, "gcp": 2,
        "docker": 2, "ci/cd": 2, "linux": 2, "git": 0.5, "python": 0.5,
    },
}


def get_all_canonical_skills():
    """Return the sorted list of canonical skill names."""
    return sorted(SKILLS_TAXONOMY.keys())

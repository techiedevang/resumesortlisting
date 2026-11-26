"""
questions.py
------------
Interview questions drawn from a candidate's scoring evidence.

Each skill has a short bank of questions. What gets asked depends on how the
resume treats the skill:

* listed only   -> "prove it" questions (a skill on the list with no project)
* proven        -> one deeper question about the work they say they did
* missing       -> a gap question: how would they get up to speed

Questions come from a fixed bank, so the same candidate always gets the same
questions and nothing here is generated or guessed.
"""

# skill -> (prove-it question, depth question)
BANK = {
    "java": ("Walk me through a program you wrote in Java. Which classes did you design and why?",
             "How do HashMap and TreeMap differ, and when would you pick each?"),
    "c": ("Describe something you wrote in C. How did you manage memory?",
          "What happens when you forget to free memory, and how would you find the leak?"),
    "c++": ("Where have you used C++ beyond a classroom exercise?",
            "What is the difference between a pointer and a reference in C++?"),
    "c#": ("What have you built with C#? Which .NET features did you use?",
           "Explain async and await in C#."),
    "python": ("Show me a Python project you are proud of. What was your part in it?",
               "What is the difference between a list and a tuple, and why does it matter?"),
    "data structures": ("Which data structure did you choose in a project, and what did you give up by choosing it?",
                        "When is a hash table a bad choice?"),
    "oop": ("Give an example from your own code where inheritance or interfaces made the design better.",
            "What is the difference between composition and inheritance?"),
    "sql": ("Write the query you used in a project to join two tables. What did the data look like?",
            "What is the difference between INNER JOIN and LEFT JOIN? When does an index help?"),
    "git": ("How did you use Git on a team project? How did you handle a merge conflict?",
            "What is the difference between merge and rebase?"),
    "linux": ("Which Linux commands do you use daily, and for what?",
              "How would you find which process is using port 8080?"),
    "javascript": ("Which JavaScript project have you built, and what did the code do?",
                   "Explain closures with a small example."),
    "typescript": ("What did TypeScript catch in your project that plain JavaScript would have missed?",
                   "What is the difference between an interface and a type alias?"),
    "react": ("Describe a React component you built. How did you manage its state?",
              "When does a component re-render, and how do you avoid needless re-renders?"),
    "angular": ("What did you build with Angular? How did you structure modules?",
                "How does dependency injection work in Angular?"),
    "vue": ("What did you build with Vue? How did you share state between components?",
            "What is the difference between computed properties and watchers?"),
    "node.js": ("What did you build on Node.js? How did you handle errors?",
                "How does the Node.js event loop work?"),
    "html/css": ("How did you make a page work on both phone and desktop?",
                 "Explain the CSS box model and how flexbox differs from grid."),
    "php": ("What did you build with PHP, and how did you prevent SQL injection?",
            "How do sessions work in PHP?"),
    "django": ("Describe the models and views of a Django app you built.",
               "What does the Django ORM do, and when would you write raw SQL instead?"),
    "flask": ("Show me the routes of a Flask app you wrote. How did you store data?",
              "How do Flask blueprints help in a larger app?"),
    "spring boot": ("What did you build with Spring Boot? How did you expose your endpoints?",
                    "What does dependency injection give you in Spring?"),
    "rest api": ("Design the endpoints for a to-do app. Which HTTP methods and status codes would you use?",
                 "What makes an endpoint idempotent? Give an example."),
    "mongodb": ("Why did you pick MongoDB over a relational database in your project?",
                "How would you model a one-to-many relationship in MongoDB?"),
    "oracle db": ("What did you do with Oracle DB? Which features did you use?",
                  "What is the difference between a view and a materialized view?"),
    "machine learning": ("Take me through an ML project from data to result. How did you measure success?",
                         "What is overfitting and how did you check for it?"),
    "deep learning": ("What model did you train, on what data, and what accuracy did you get?",
                      "Why do we need activation functions?"),
    "nlp": ("What NLP task did you work on? How did you prepare the text?",
            "What is the difference between stemming and lemmatisation?"),
    "computer vision": ("What did you build with images? Which dataset did you use?",
                        "How does a convolution layer work?"),
    "pytorch": ("Describe a model you trained in PyTorch. How did you write the training loop?",
                "What does loss.backward() do?"),
    "tensorflow": ("What did you train in TensorFlow, and how did you deploy or save it?",
                   "What is the difference between a Keras Sequential and a functional model?"),
    "scikit-learn": ("Which scikit-learn models did you compare, and how did you pick one?",
                     "Why should you fit a scaler only on the training data?"),
    "pandas": ("How did you clean a messy dataset in pandas? What problems did you find?",
               "What is the difference between loc and iloc?"),
    "numpy": ("Where did you use NumPy instead of plain Python lists, and why?",
              "What is broadcasting?"),
    "llm": ("What did you build with a large language model? How did you check its answers?",
            "How do you reduce hallucinations in an LLM application?"),
    "rag": ("Explain the pipeline of a RAG system you built. How did you split documents?",
            "How would you tell whether retrieval or generation caused a wrong answer?"),
    "huggingface": ("Which Hugging Face model did you use, and how did you adapt it?",
                    "What does a tokenizer do before the model sees the text?"),
    "statistics": ("Describe an analysis where you used a statistical test. Why that test?",
                   "What does a p-value tell you, and what does it not?"),
    "data analysis": ("Describe a dataset you analysed. What question did you answer?",
                      "How do you handle missing values, and what are the trade-offs?"),
    "excel": ("Which Excel formulas or pivot tables did you use in a real task?",
              "What is the difference between VLOOKUP and INDEX/MATCH?"),
    "power bi": ("Show me a Power BI dashboard you built. Who was it for?",
                 "What is the difference between a measure and a calculated column?"),
    "tableau": ("Which Tableau dashboard did you build, and what decision did it support?",
                "When would you use a blended data source instead of a join?"),
    "r": ("What did you analyse in R, and with which packages?",
          "What is a data frame, and how does it differ from a matrix?"),
    "docker": ("What did you put in a container? Show me the Dockerfile's main steps.",
               "What is the difference between an image and a container?"),
    "kubernetes": ("What did you deploy on Kubernetes? How did you expose it?",
                   "What is the difference between a Deployment and a StatefulSet?"),
    "terraform": ("What infrastructure did you define in Terraform? How did you manage its state?",
                  "What does terraform plan do before apply?"),
    "ci/cd": ("Describe a pipeline you set up. Which stages ran on every commit?",
              "How do you stop a failed test from reaching production?"),
    "aws": ("Which AWS services did you use, and how did they connect?",
            "How would you secure an S3 bucket that serves a website?"),
    "azure": ("Which Azure services did you use in a project?",
              "What is the difference between a virtual machine and an App Service?"),
    "gcp": ("Which Google Cloud services did you use, and for what?",
            "When would you choose BigQuery over Cloud SQL?"),
    "go": ("What did you write in Go? How did you use goroutines?",
           "What is the difference between a goroutine and a thread?"),
    "kotlin": ("What did you build in Kotlin? Was it for Android?",
               "What does null safety in Kotlin prevent?"),
    "communication": ("Tell me about a time you explained something technical to a non-technical person.",
                      "How do you handle disagreement with a teammate over a design?"),
    "leadership": ("Describe a time you led a team or a task. What was the result?",
                   "How do you handle a teammate who is not delivering?"),
    "problem solving": ("Describe the hardest bug you fixed. How did you find the cause?",
                        "How do you approach a problem you have never seen before?"),
    "project management": ("How did you plan and track a project with a deadline?",
                           "What do you do when a deadline is at risk?"),
}

GAP_QUESTION = "The role asks for {skill}, which we did not find on your resume. How would you get up to speed on it, and what have you done that is close?"
GENERIC_PROVE = "Your resume lists {skill}. Which project or job used it, and what did you do with it?"
GENERIC_DEPTH = "Tell me about the most difficult thing you did with {skill}."


def _prove(skill: str) -> str:
    return BANK[skill][0] if skill in BANK else GENERIC_PROVE.format(skill=skill)


def _depth(skill: str) -> str:
    return BANK[skill][1] if skill in BANK else GENERIC_DEPTH.format(skill=skill)


def build_questions(evidence: dict, missing_skills: list, flags: list = None,
                    limit: int = 8) -> list:
    """
    Return [{"skill", "kind", "question"}] with `kind` one of "prove", "depth",
    "gap", "integrity". Questions to probe unproven claims come first, then
    gaps, then one depth question per proven skill.
    """
    flags = flags or []
    out = []

    for code in (f.get("code") for f in flags):
        if code == "jd_copy":
            out.append({"skill": "", "kind": "integrity",
                        "question": "Your resume shares a lot of wording with the job description. In your own words, what did you actually do in your most recent project?"})
            break

    for skill in evidence.get("listed_skills", []):
        out.append({"skill": skill, "kind": "prove", "question": _prove(skill)})
    for skill in missing_skills:
        out.append({"skill": skill, "kind": "gap", "question": GAP_QUESTION.format(skill=skill)})
    for skill in evidence.get("proven_skills", []):
        out.append({"skill": skill, "kind": "depth", "question": _depth(skill)})
    return out[:limit]

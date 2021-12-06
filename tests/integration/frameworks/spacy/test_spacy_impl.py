import random
import typing as t
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import spacy
import yaml
from spacy.training import Example
from spacy.util import minibatch

import bentoml.spacy
from bentoml.exceptions import MissingDependencyException

if TYPE_CHECKING:
    from bentoml._internal.models import ModelStore

current_file = Path(__file__).parent

MODEL_NAME = __name__.split(".")[-1]
train_data: t.List[t.Tuple[str, t.Dict[str, t.List[t.Tuple[int, int, str]]]]] = [
    ("Google has changed the logo of its apps", {"entities": [(0, 6, "ORG")]}),
    ("Facebook has introduced a new app!", {"entities": [(0, 8, "ORG")]}),
    ("Amazon has partnered with small businesses.", {"entities": [(0, 6, "ORG")]}),
]

test_json: t.Dict[str, str] = {"text": "Google cloud is now a separate entity."}


def predict_json(model: "spacy.language.Language", json: t.Dict[str, str]) -> str:
    return model(json["text"]).text


@pytest.fixture(scope="module")
def spacy_model():
    examples = []
    model = spacy.blank("en")
    if "ner" not in model.pipe_names:
        ner = model.add_pipe("ner", last=True)
    else:
        ner = model.get_pipe("ner")

    for text, annotations in train_data:
        examples.append(Example.from_dict(model.make_doc(text), annotations))  # noqa
        for ent in annotations.get("entities"):
            ner.add_label(ent[2])

    other_pipes = [pipe for pipe in model.pipe_names if pipe != "ner"]

    with model.disable_pipes(*other_pipes):
        optimizer = model.begin_training()
        for _ in range(10):
            random.shuffle(examples)
            for batch in minibatch(examples, size=8):
                model.update(batch, sgd=optimizer)

    return model


def test_spacy_save_load(spacy_model, modelstore: "ModelStore"):
    tag = bentoml.spacy.save(MODEL_NAME, spacy_model, model_store=modelstore)
    model_info = modelstore.get(tag)
    assert "meta.json" in [_.name for _ in Path(model_info.path).iterdir()]

    spacy_loaded = bentoml.spacy.load(tag, model_store=modelstore)
    assert predict_json(spacy_loaded, test_json) == test_json["text"]
    with pytest.raises(EnvironmentError):
        _ = bentoml.spacy.load_project(tag, model_store=modelstore)


def test_spacy_load_project(modelstore: "ModelStore"):
    tag = bentoml.spacy.projects(
        "test",
        "clone",
        name="integrations/huggingface_hub",
        repo_or_store="https://github.com/aarnphm/projects",
        model_store=modelstore,
    )
    path = bentoml.spacy.load_project(tag, model_store=modelstore)
    assert "project.yml" in [f.name for f in Path(path).iterdir()]
    with pytest.raises(EnvironmentError):
        _ = bentoml.spacy.load(tag, model_store=modelstore)


def test_spacy_load_missing_deps_exc(modelstore: "ModelStore"):
    nlp = spacy.load("en_core_web_sm")
    tag = bentoml.spacy.save("test_spacy", nlp, model_store=modelstore)
    info = modelstore.get(tag)
    parent = info.path
    with Path(parent, "model.yaml").open("r") as f:
        content = yaml.safe_load(f)
    content["options"]["additional_requirements"] = ["spacy-transformers>=1.0.3,<1.1.0"]
    with Path(parent, "model.yaml").open("w") as of:
        yaml.safe_dump(content, of)
    with pytest.raises(MissingDependencyException):
        _ = bentoml.spacy.load(tag, model_store=modelstore)
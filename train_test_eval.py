import logging
import pprint

import keras
import tensorflow as tf
from rouge import Rouge
from tqdm import tqdm

from batcher import Vocab, batcher
from model import PGN
from test_helper import beam_decode
from training_helper import ModelTrainer


def train(params):
    assert params["mode"].lower() == "train", "change training mode to 'train'"

    logging.info("Building the model ...")
    model = PGN(params)

    logging.info("Building Optimizer ...")
    optimizer = keras.optimizers.Adagrad(
        learning_rate=params["learning_rate"],
        initial_accumulator_value=params["adagrad_init_acc"],
        clipnorm=params["max_grad_norm"],
    )

    print("Creating the vocab ...")
    vocab = Vocab(params["vocab_path"], params["vocab_size"])

    print("Creating the batcher ...")
    dataset_v2 = batcher(params["data_dir"], vocab, params)

    print("Creating the checkpoint manager")
    checkpoint_dir = "{}".format(params["checkpoint_dir"])
    ckpt = tf.train.Checkpoint(
        step=tf.Variable(0),
        model=model,
        # optimizer=optimizer,
    )
    ckpt_manager = tf.train.CheckpointManager(ckpt, checkpoint_dir, max_to_keep=5)

    print("latest checkpoint", ckpt_manager.latest_checkpoint)
    status = ckpt.restore(ckpt_manager.latest_checkpoint).expect_partial()

    # model.summary()
    # status.assert_existing_objects_matched()
    status.assert_consumed()

    if ckpt_manager.latest_checkpoint:
        print("Restored from {}".format(ckpt_manager.latest_checkpoint))
    else:
        print("Initializing from scratch.")

    logging.info("Starting the training ...")
    model_trainer = ModelTrainer(params, model, dataset_v2)
    model_trainer.execute(ckpt, ckpt_manager, "output.txt", vocab, optimizer)


def test(params):
    assert params["mode"].lower() in ["test", "eval"], "change training mode to 'test' or 'eval'"
    assert params["beam_size"] == params["batch_size"], "Beam size must be equal to batch_size, change the params"

    logging.info("Building the model ...")
    model = PGN(params)

    print("Creating the vocab ...")
    vocab = Vocab(params["vocab_path"], params["vocab_size"])

    print("Creating the batcher ...")
    b = batcher(params["data_dir"], vocab, params)

    print("Creating the checkpoint manager")
    checkpoint_dir = "{}".format(params["checkpoint_dir"])
    ckpt = tf.train.Checkpoint(step=tf.Variable(0), model=model)
    ckpt_manager = tf.train.CheckpointManager(ckpt, checkpoint_dir, max_to_keep=11)

    path = params["model_path"] if params["model_path"] else ckpt_manager.latest_checkpoint
    ckpt.restore(path)
    print("Model restored")

    for batch in b:
        yield beam_decode(model, batch, vocab, params)


def test_and_save(params):
    assert params["test_save_dir"], "provide a dir where to save the results"
    gen = test(params)
    with tqdm(total=params["num_to_test"], position=0, leave=True) as pbar:
        for i in range(params["num_to_test"]):
            trial = next(gen)
            with open(params["test_save_dir"] + "/article_" + str(i) + ".txt", "w") as f:
                f.write("article:\n")
                f.write(trial.text)
                f.write("\n\nabstract:\n")
                f.write(trial.abstract)
            pbar.update(1)


def evaluate(params):
    gen = test(params)
    reals = []
    preds = []
    with tqdm(total=params["max_num_to_eval"], position=0, leave=True) as pbar:
        for i in range(params["max_num_to_eval"]):
            trial = next(gen)
            reals.append(trial.real_abstract)
            preds.append(trial.abstract)
            pbar.update(1)
    r = Rouge()
    scores = r.get_scores(preds, reals, avg=True)
    print("\n\n")
    pprint.pprint(scores)

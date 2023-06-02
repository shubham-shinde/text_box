import torch
from torch import optim
from tqdm import tqdm
from pathlib import Path
from models import get_model
from dataset import get_dataset
from helper import model_text, model_out_to_text
import wandb
import sys
import os

absolute_path = Path(os.path.dirname(__file__))


def train(config, log, device):

    files = [os.path.join(dp, f) for dp, _, filenames in os.walk(
        absolute_path/'../datasets/mnt/') for f in filenames if os.path.splitext(f)[1] in ['.jpg', '.jpeg', '.png']]
    print('full dataset count:', len(files))

    train_img_files = files
    if config['train_size'] is not None:
        train_img_files = files[:config['train_size']]

    eval_image_files = []
    if config['eval_size'] is not None:
        eval_image_files = files[-config['eval_size']:]

    test_image_files = [os.path.join(dp, f) for dp, _, filenames in os.walk(
        absolute_path/'../datasets/detect_val_data') for f in filenames if os.path.splitext(f)[1] in ['.jpg', '.jpeg', '.png']]

    print('train_data_sz: ', len(train_img_files),
          'eval_data_sz: ', len(eval_image_files))

    Model = get_model(config['model'])
    Dataset = get_dataset(config['dataset'])

    model = Model(Dataset.clasess).to(device)

    wandb.init(
        # set the wandb project where this run will be logged
        project="text_detector_1",
        config=config,
        mode='disabled' if log == False else 'run'
    )

    # dataset
    dataset = Dataset(train_img_files, only_synt=False)

    eval_dataset = Dataset(eval_image_files, only_synt=False)

    test_dataset = Dataset(test_image_files, only_synt=False)

    test_dataloader = torch.utils.data.DataLoader(
        test_dataset, batch_size=12, shuffle=True)
    eval_dataloader = torch.utils.data.DataLoader(eval_dataset, batch_size=256)
    dataloader = torch.utils.data.DataLoader(
        dataset, batch_size=config['batch_size'])

    # model test
    # for img, label, lengths in eval_dataloader:
    #     out, loss = model(img, targets=label, lengths=lengths)
    #     print(out.shape, loss)

    # # train setting
    optimizer = optim.Adam(model.parameters(), lr=config['learning_rate'])
    scheduler = optim.lr_scheduler.StepLR(
        optimizer, step_size=config['lr_step_size'], gamma=config['lr_gamma'])

    # train loop
    lrs = []
    losses = []
    for epoch in range(config['epochs']):
        epoch_loss = 0
        batches = 0
        print('epoch -', epoch)
        lrs.append(optimizer.param_groups[0]['lr'])
        print('learning rate', lrs[-1])
        pbar = tqdm(dataloader)
        for img, targets, lengths in pbar:
            model.train()
            targets = targets.to(device)
            img = img.to(device)

            # data check
            # temp_img = img[0].permute([1, 2, 0])
            # cv2.imshow(model_text(targets[0]), temp_img.cpu().detach().numpy())
            # cv2.waitKey(0)
            # cv2.destroyAllWindows()

            lengths = lengths.to(device)
            batches += 1
            optimizer.zero_grad()
            _, loss = model(img.to(device), targets, lengths)
            loss.backward()
            optimizer.step()
            epoch_loss += loss.item()

            # eval_loss calculation
            pbar.set_postfix(
                {'loss': epoch_loss/batches})

        with torch.no_grad():
            model.eval()
            batch_loss = torch.tensor([model(eimg.to(device), etarget.to(device), elen.to(device))[1]
                                      for eimg, etarget, elen in dataloader]).mean().item()
            eval_loss = torch.tensor([model(eimg.to(device), etarget.to(device), elen.to(device))[1]
                                      for eimg, etarget, elen in eval_dataloader]).mean().item()
            losses.append(batch_loss)

            print('train')
            train_acc = calc_acc(model, dataloader, Dataset)
            print('test')
            test_acc = calc_acc(model, test_dataloader, Dataset)
            print('eval')
            eval_acc = calc_acc(model, eval_dataloader, Dataset)

        pp = {"eval_acc": eval_acc, "batch_loss": batch_loss,
              "test_acc": test_acc, "eval_loss": eval_loss, "train_acc": train_acc}

        print(pp)
        wandb.log(pp)

        scheduler.step()
        print('epoch_loss', losses[-1])
    wandb.finish()
    torch.save(model, f'{config["model"]}.pt')


def calc_acc(model, dataloader, Dataset, mx=12):
    model.eval()
    eval_acc = 0
    for img, target, lengths in dataloader:
        out, tloss = model(img.to(device), target.to(
            device), lengths.to(device))
        print('test_loss:', tloss)
        acc = 0
        words = 0
        counter = 0
        for ot, tg in zip(out.cpu().transpose(0, 1), target):
            counter += 1
            tg = model_text(tg, Dataset.letters)
            ot = model_text(ot.squeeze(), Dataset.letters,
                            max_needed=True)
            rot = model_out_to_text(ot)
            for i, w in enumerate(tg):
                words += 1
                acc += int(w == rot[i] if len(rot) > i else False)
            print(tg, ot, rot)
            if counter >= mx:
                break
        eval_acc = acc/words
        break
    return eval_acc


if __name__ == '__main__':
    log = '--log' in sys.argv

    config = {
        'learning_rate': 0.0001,
        'epochs': 50,
        'train_size': 100*(10**4),
        'eval_size': 10**3,
        'lr_step_size': 20,
        'lr_gamma': 0.8,
        'batch_size': 32,
        'model': 'base',
        'dataset': 'mnt'
    }

    device = 'cuda:0' if torch.cuda.is_available() else 'cpu'
    train(config, log, device)
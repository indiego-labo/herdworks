# Herdworks (hw)

Give a coding task to a Project in one command. One agent builds it, a different agent checks
it works, and you get a draft pull request (or a verified branch) with the proof.

## Everyday commands

    hw run -p PROJECT "what you want. Done when ..."   build, check, verify; ends done, blocked or failed
    hw run -p PROJECT --detach "..."                 the same in the background
    hw status TASK                                   stage, elapsed, tokens, last action, branch or pull request
    hw watch [TASK]                                  follow a task until it ends
    hw run -p PROJECT --resume TASK                  continue a blocked or interrupted task
    hw say PROJECT --task TASK "your decision"       answer a blocked task; it resumes
    hw status                                        what is running now
    hc attach NAME                                   watch an agent live (names from hw status)

Budgets: add --max-minutes N or --max-tokens N to hw run. --json on run, status and watch.

## Talking to a coordinator instead

    hw say PROJECT "what you want. Done when ..."   give a task, or answer a question
    hw read PROJECT                                  the coordinator's replies
    hw wait PROJECT                                  wait for the next reply, then print it
    hw tasks PROJECT                                 every task and its status

Each reply starts with its kind: REPLY (progress), QUESTION (it needs your decision; answer
with hw say), DONE (finished, with the pull request) or PROBLEM (needs the owner).

## Setting up

    hw setup                  sign in, pick a model, add a Project; safe to run again
    hw setup --check          only report what is missing
    hw project add NAME --github owner/repo       add a Project from GitHub; hw clones it
    hw project add NAME --repo PATH --base main   add a checkout you already have
    hw say NAME --base BRANCH "what you want"     start that task from another branch
    hw rules                  the house rules workers follow
    hw skills                 skills workers can load, and rules naming a missing one

## More help

    hw help agent         instructions for an AI agent (Claude, Codex, a ChatGPT dot) using hw
    hw help models        choose opencode or Codex, and which model, per role
    hw help rules         change how workers build and verify
    hw help server        run Herdworks on an always-on Linux machine
    hw help automations   pick up GitHub issues or run on a schedule
    hw help reference     every command and setting in detail
    hw COMMAND --help     the options of one command

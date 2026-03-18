from sdtool.workflow import StepStatus, WorkflowController


def test_start_operation_marks_first_step_running() -> None:
    controller = WorkflowController()
    controller.start_operation(
        "save",
        [
            ("step1", "detail1"),
            ("step2", "detail2"),
            ("step3", "detail3"),
        ],
    )

    assert controller.operation_name == "save"
    assert len(controller.steps) == 3
    assert controller.steps[0].status == StepStatus.RUNNING
    assert controller.steps[1].status == StepStatus.PENDING
    assert controller.steps[2].status == StepStatus.PENDING


def test_set_running_step_marks_prior_steps_complete() -> None:
    controller = WorkflowController()
    controller.start_operation(
        "shrink",
        [
            ("step1", "detail1"),
            ("step2", "detail2"),
            ("step3", "detail3"),
            ("step4", "detail4"),
        ],
    )

    controller.set_running_step(2)

    assert controller.steps[0].status == StepStatus.COMPLETE
    assert controller.steps[1].status == StepStatus.COMPLETE
    assert controller.steps[2].status == StepStatus.RUNNING
    assert controller.steps[3].status == StepStatus.PENDING


def test_apply_progress_completes_earlier_steps() -> None:
    controller = WorkflowController()
    controller.start_operation(
        "write",
        [
            ("step1", "detail1"),
            ("step2", "detail2"),
            ("step3", "detail3"),
            ("step4", "detail4"),
        ],
    )

    controller.apply_progress(55)

    assert controller.steps[0].status == StepStatus.COMPLETE
    assert controller.steps[1].status == StepStatus.COMPLETE
    assert controller.steps[2].status == StepStatus.RUNNING
    assert controller.steps[3].status == StepStatus.PENDING


def test_complete_operation_marks_all_steps_complete() -> None:
    controller = WorkflowController()
    controller.start_operation(
        "shrink",
        [
            ("step1", "detail1"),
            ("step2", "detail2"),
        ],
    )

    controller.complete_operation()

    assert all(step.status == StepStatus.COMPLETE for step in controller.steps)


def test_fail_operation_marks_running_step_failed() -> None:
    controller = WorkflowController()
    controller.start_operation(
        "verify",
        [
            ("step1", "detail1"),
            ("step2", "detail2"),
        ],
    )

    controller.fail_operation()

    assert controller.steps[0].status == StepStatus.FAILED
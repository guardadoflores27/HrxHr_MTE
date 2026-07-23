from django.db import models
from core.models import SubProcess


class WindingMachine(models.Model):
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Winding Machine"

    


class MachineAssignment(models.Model):
    subprocess = models.ForeignKey(SubProcess, on_delete=models.CASCADE)
    machine = models.ForeignKey(WindingMachine, on_delete=models.CASCADE)
    date = models.DateField()


    class Meta:
        verbose_name = "Machine Assignment"
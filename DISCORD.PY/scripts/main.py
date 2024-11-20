import discord
from discord.ext import commands, tasks
from discord import ButtonStyle, app_commands
from discord.ui import Button, View
from datetime import datetime, timedelta
import asyncio
from datetime import datetime, timedelta
import json
import os
from discord.ext import commands
from discord import Role

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True  # Nécessaire pour que le bot gère les rôles

# Préfixe pour les commandes
bot = commands.Bot(command_prefix='.', intents=intents)

# Change un role a un autre pour tout se qu'on le role
@bot.command()
@commands.has_any_role("→ Empereur", "→ Ministre")  # Liste des rôles autorisés
async def role(ctx, ancien_role: discord.Role, nouveau_role: discord.Role):
    """
    Remplace un rôle par un autre pour tous les membres ayant ce rôle.
    :param ctx: contexte de la commande
    :param ancien_role: rôle à retirer
    :param nouveau_role: rôle à ajouter
    """
    try:
        membres_modifiés = []

        # Parcourir tous les membres ayant l'ancien rôle
        for membre in ctx.guild.members:
            if ancien_role in membre.roles:
                # Retirer l'ancien rôle et ajouter le nouveau
                await membre.remove_roles(ancien_role)
                await membre.add_roles(nouveau_role)
                membres_modifiés.append(membre)

        await ctx.send(f"Le rôle {ancien_role.name} a été remplacé par {nouveau_role.name} pour {len(membres_modifiés)} membre(s).")
    except discord.Forbidden:
        await ctx.send("Je n'ai pas les permissions nécessaires pour gérer les rôles.")
    except discord.HTTPException as e:
        await ctx.send(f"Une erreur s'est produite : {e}")

# Chemin du fichier JSON pour sauvegarder les tâches
TASKS_FILE = "role_tasks.json"

# Dictionnaire pour stocker les tâches planifiées en mémoire
role_tasks = {}

def save_tasks_to_file():
    """Sauvegarde les tâches planifiées dans un fichier JSON."""
    global role_tasks  # Ajout de la déclaration globale
    with open(TASKS_FILE, "w") as f:
        json.dump(role_tasks, f, indent=4, default=str)

def load_tasks_from_file():
    """Charge les tâches planifiées depuis un fichier JSON."""
    if os.path.exists(TASKS_FILE):
        with open(TASKS_FILE, "r") as f:
            tasks = json.load(f)
            # Convertir les dates en objets datetime
            for task_id, details in tasks.items():
                details["end_time"] = datetime.fromisoformat(details["end_time"])
            return tasks
    return {}

# Change un role auto 
@bot.event
async def on_ready():
    global role_tasks  # Ajout de la déclaration globale
    print(f"{bot.user.name} est prêt et connecté!")

    # Charger les tâches depuis le fichier et planifier celles encore valides
    role_tasks = load_tasks_from_file()
    for task_id, details in list(role_tasks.items()):
        ancien_role = bot.get_guild(details["guild_id"]).get_role(details["ancien_role"])
        nouveau_role = bot.get_guild(details["guild_id"]).get_role(details["nouveau_role"])
        remaining_time = (details["end_time"] - datetime.now()).total_seconds()

        if remaining_time > 0:
            # Planifier les tâches valides
            bot.loop.create_task(remplacer_role_apres_duree(
                ancien_role=ancien_role, 
                nouveau_role=nouveau_role, 
                guild_id=details["guild_id"],
                remaining_time=remaining_time,
                task_id=task_id
            ))
        else:
            # Supprimer les tâches expirées
            del role_tasks[task_id]
    save_tasks_to_file()

@bot.command()
@commands.has_any_role("→ Empereur", "→ Ministre")  # Liste des rôles autorisés
async def rolea(ctx, ancien_role: discord.Role, nouveau_role: discord.Role, duree: str):
    """
    Planifie le remplacement d'un rôle par un autre après une durée spécifiée.
    """
    global role_tasks  # Ajout de la déclaration globale
    try:
        # Convertir la durée en secondes
        multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
        unit = duree[-1]
        if unit not in multipliers:
            await ctx.send("Unité invalide. Utilisez 's', 'm', 'h', 'd', ou 'w'.")
            return

        amount = int(duree[:-1])
        seconds = amount * multipliers[unit]
        end_time = datetime.now() + timedelta(seconds=seconds)

        # Ajouter la tâche au dictionnaire
        task_id = f"{ancien_role.id}->{nouveau_role.id}"
        if task_id in role_tasks:
            await ctx.send(f"Une tâche pour remplacer {ancien_role.name} par {nouveau_role.name} existe déjà.")
            return

        role_tasks[task_id] = {
            "ancien_role": ancien_role.id,
            "nouveau_role": nouveau_role.id,
            "end_time": end_time.isoformat(),
            "guild_id": ctx.guild.id
        }
        save_tasks_to_file()

        # Lancer la tâche asynchrone
        bot.loop.create_task(remplacer_role_apres_duree(
            ancien_role=ancien_role, 
            nouveau_role=nouveau_role, 
            guild_id=ctx.guild.id,
            remaining_time=seconds,
            task_id=task_id
        ))

        await ctx.send(f"Tâche planifiée : {ancien_role.name} sera remplacé par {nouveau_role.name} dans {duree}.")
    except ValueError:
        await ctx.send("Durée invalide. Assurez-vous d'utiliser un format comme '2w', '3d', etc.")

@bot.event
async def on_member_update(before, after):
    """Surveille les mises à jour des membres, comme l'ajout de rôles."""
    global role_tasks
    for role in after.roles:
        if role not in before.roles:  # Si le rôle a été ajouté
            task_id = f"{after.guild.id}->{role.id}"
            if task_id in role_tasks:
                details = role_tasks[task_id]
                # Calculer la durée restante à partir du moment où le rôle a été ajouté
                start_time = datetime.now()  # L'heure actuelle est le début
                end_time = start_time + timedelta(seconds=(details["remaining_time"]))
                role_tasks[task_id]["end_time"] = end_time.isoformat()

                # Planifier la tâche à effectuer après la durée spécifiée
                bot.loop.create_task(remplacer_role_apres_duree(
                    ancien_role=bot.get_guild(after.guild.id).get_role(details["ancien_role"]),
                    nouveau_role=bot.get_guild(after.guild.id).get_role(details["nouveau_role"]),
                    guild_id=after.guild.id,
                    remaining_time=(details["remaining_time"]),
                    task_id=task_id
                ))
                save_tasks_to_file()

async def remplacer_role_apres_duree(ancien_role, nouveau_role, guild_id, remaining_time, task_id):
    """Effectue le remplacement du rôle après la durée spécifiée."""
    global role_tasks  # Ajout de la déclaration globale
    await asyncio.sleep(remaining_time)
    try:
        guild = bot.get_guild(guild_id)
        for membre in guild.members:
            if ancien_role in membre.roles:
                await membre.remove_roles(ancien_role)
                await membre.add_roles(nouveau_role)

        # Supprimer la tâche terminée du dictionnaire
        if task_id in role_tasks:
            del role_tasks[task_id]
        save_tasks_to_file()

        channel = guild.system_channel
        if channel:
            await channel.send(f"Le rôle {ancien_role.name} a été remplacé par {nouveau_role.name}.")
    except discord.Forbidden:
        print("Permissions insuffisantes pour gérer les rôles.")
    except discord.HTTPException as e:
        print(f"Une erreur HTTP s'est produite : {e}")

@bot.command()
@commands.has_any_role("→ Empereur", "→ Ministre")  # Liste des rôles autorisés
async def unrolea(ctx, ancien_role: discord.Role, nouveau_role: discord.Role):
    """Supprime une tâche de remplacement de rôle planifiée."""
    global role_tasks
    try:
        task_id = f"{ancien_role.id}->{nouveau_role.id}"
        if task_id in role_tasks:
            del role_tasks[task_id]
            save_tasks_to_file()
            await ctx.send(f"Tâche supprimée : {ancien_role.name} ne sera pas remplacé par {nouveau_role.name}.")
        else:
            await ctx.send("Aucune tâche planifiée pour ce remplacement.")
    except Exception as e:
        await ctx.send(f"Une erreur s'est produite : {e}")

@bot.command()
@commands.has_any_role("→ Empereur", "→ Ministre")  # Liste des rôles autorisés
async def listroles(ctx):
    """Affiche la liste des tâches de remplacement planifiées."""
    global role_tasks  # Ajout de la déclaration globale
    if not role_tasks:
        await ctx.send("Aucune tâche de remplacement de rôle planifiée.")
        return

    message = "**Tâches planifiées :**\n"
    for task_id, details in role_tasks.items():
        ancien_role = ctx.guild.get_role(details["ancien_role"])
        nouveau_role = ctx.guild.get_role(details["nouveau_role"])
        end_time = details["end_time"]
        message += f"- {ancien_role.name} -> {nouveau_role.name} (remplacement à {end_time})\n"
    await ctx.send(message)

@bot.event
async def on_ready():
    print(f"Connecté en tant que {bot.user}")


if __name__ == "__main__":
    bot.run("MTMwMTMzODkyMTQxNzk2NTY5MQ.GicJhC.nyIQyHzri7wHT4HNaAAhvjXaEAPY0x5OnBPVWc")
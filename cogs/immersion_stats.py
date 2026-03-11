import io
import os
import requests
import textwrap
import numpy as np
import seaborn as sns
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib import colormaps
from matplotlib import patches
import matplotlib.colors as mcolors
import matplotlib.font_manager as fm
import discord
from discord.ext import commands
from typing import Optional
from datetime import datetime
import asyncio
from PIL import Image
from lib.media_types import MEDIA_TYPES, LOG_CHOICES
from lib.bot import JouzuBot
from .username_fetcher import get_username_db
from lib.anilist_autocomplete import query_anilist, CACHED_ANILIST_TITLE_QUERY
from lib.vndb_autocomplete import query_vndb, CACHED_VNDB_TITLE_QUERY
import matplotlib

matplotlib.use("Agg")

GET_USER_LOGS_FOR_PERIOD_QUERY_BASE = """
    SELECT media_type, amount_logged, time_logged, log_date
    FROM logs
    WHERE user_id = ? AND log_date BETWEEN ? AND ?
"""

GET_USER_LOGS_FOR_PERIOD_QUERY_WITH_MEDIA_TYPE = (
    GET_USER_LOGS_FOR_PERIOD_QUERY_BASE + " AND media_type = ? ORDER BY log_date;"
)
GET_USER_LOGS_FOR_PERIOD_QUERY_BASE += " ORDER BY log_date;"

GET_USER_LOGS_FOR_PERIOD_WITH_NAME_QUERY_BASE = """
    SELECT media_type, media_name, amount_logged, time_logged, log_date
    FROM logs
    WHERE user_id = ? AND log_date BETWEEN ? AND ?
"""

GET_USER_LOGS_FOR_PERIOD_WITH_NAME_QUERY_WITH_MEDIA_TYPE = (
    GET_USER_LOGS_FOR_PERIOD_WITH_NAME_QUERY_BASE
    + " AND media_type = ? ORDER BY log_date;"
)
GET_USER_LOGS_FOR_PERIOD_WITH_NAME_QUERY_BASE += " ORDER BY log_date;"


def modify_cmap(cmap_name, zero_color="black", nan_color="black", truncate_high=0.7):
    """
    Modify a colormap to have specific colors for 0 and NaN values, and truncate the upper range.
    """
    base_cmap = colormaps[cmap_name]
    truncated_cmap = base_cmap(np.linspace(0, truncate_high, base_cmap.N))
    modified_cmap = mcolors.ListedColormap(truncated_cmap)
    modified_cmap.colors[0] = mcolors.to_rgba(zero_color)

    # Set NaN color
    modified_cmap.set_bad(color=nan_color)

    return modified_cmap


def embedded_info(df: pd.DataFrame) -> tuple:
    time_total = df["time_logged"].sum()
    breakdown = (
        df.groupby("media_type")
        .agg({"amount_logged": "sum", "time_logged": "sum"})
        .reset_index()
    )
    breakdown["unit_name"] = breakdown["media_type"].apply(
        lambda x: MEDIA_TYPES[x]["unit_name"]
    )
    breakdown_str = "\n".join(
        [
            f"{row['media_type']}: {row['amount_logged']} {row['unit_name']}{'s' if row['amount_logged'] > 1 else ''} → {round(row['time_logged'], 2)} minutes"
            for _, row in breakdown.iterrows()
        ]
    )

    return breakdown_str, time_total


def set_plot_styles():
    # Build font list with Japanese fonts, emoji font, and fallback
    font_list = []

    # Register bundled Japanese font
    jp_font_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "fonts",
        "NotoSansCJKjp-Regular.otf",
    )
    if os.path.exists(jp_font_path):
        try:
            fm.fontManager.addfont(jp_font_path)
            jp_font_prop = fm.FontProperties(fname=jp_font_path)
            font_list.append(jp_font_prop.get_name())
        except Exception:
            pass

    # Register and use NotoEmoji font for emoji support
    emoji_font_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "fonts",
        "NotoEmoji-VariableFont_wght.ttf",
    )
    if os.path.exists(emoji_font_path):
        try:
            fm.fontManager.addfont(emoji_font_path)
            emoji_font_prop = fm.FontProperties(fname=emoji_font_path)
            font_list.append(emoji_font_prop.get_name())
        except Exception:
            pass

    # Add fallback fonts
    font_list.extend(["DejaVu Sans", "sans-serif"])
    plt.rcParams["font.family"] = font_list

    plt.rcParams.update(
        {
            "axes.titlesize": 20,
            "axes.titleweight": "bold",
            "axes.labelsize": 14,
            "axes.labelweight": "bold",
            "xtick.labelsize": 12,
            "ytick.labelsize": 12,
            "axes.facecolor": "#303446",
            "figure.facecolor": "#303446",
            "text.color": "#c6d0f5",
            "axes.labelcolor": "#c6d0f5",
            "xtick.color": "#c6d0f5",
            "ytick.color": "#c6d0f5",
        }
    )


def process_bar_data(
    df: pd.DataFrame, from_date: datetime, to_date: datetime, immersion_type: str = None
) -> tuple:
    bar_df = df[from_date:to_date]
    if immersion_type:
        bar_df = bar_df.pivot_table(
            index=bar_df.index.date,
            columns="media_type",
            values="amount_logged",
            aggfunc="sum",
            fill_value=0,
        )
    else:
        bar_df = bar_df.pivot_table(
            index=bar_df.index.date,
            columns="media_type",
            values="time_logged",
            aggfunc="sum",
            fill_value=0,
        )
    bar_df.index = pd.DatetimeIndex(bar_df.index)

    time_frame = pd.date_range(bar_df.index.date.min(), to_date, freq="D")
    bar_df = bar_df.reindex(time_frame, fill_value=0)

    if not isinstance(bar_df.index, pd.DatetimeIndex):
        bar_df.index = pd.to_datetime(bar_df.index)

    if len(bar_df) > 365 * 2:
        df_plot = bar_df.resample("QE").sum()
        x_lab = " (year-quarter)"
        date_labels = df_plot.index.map(
            lambda date: f"{date.year}-Q{(date.month - 1) // 3 + 1}"
        )
    elif len(bar_df) > 30 * 7:
        df_plot = bar_df.resample("ME").sum()
        x_lab = " (year-month)"
        date_labels = df_plot.index.strftime("%Y-%m")
    elif len(bar_df) > 31:
        df_plot = bar_df.resample("W").sum()
        x_lab = " (year-week)"
        date_labels = df_plot.index.strftime("%Y-%W")
    else:
        df_plot = bar_df
        date_labels = df_plot.index.strftime("%Y-%m-%d")
        x_lab = ""

    return df_plot, x_lab, date_labels


def process_heatmap_data(
    df: pd.DataFrame, from_date: datetime, to_date: datetime
) -> dict:
    df = df.resample("D").sum(numeric_only=True)
    full_date_range = pd.date_range(
        start=datetime(df.index.year.min(), 1, 1),
        end=datetime(df.index.year.max(), 12, 31),
    )
    df = df.reindex(full_date_range, fill_value=0)
    df["day"] = df.index.weekday
    df["year"] = df.index.year

    # Generate heatmap data for each year
    heatmap_data = {}
    for year, group in df.groupby("year"):
        year_begins_on = group.index.date.min().weekday()
        group["week"] = (group.index.dayofyear + year_begins_on - 1) // 7
        year_data = group.pivot_table(
            index="day",
            columns="week",
            values="time_logged",
            aggfunc="sum",
            fill_value=np.nan,
        )

        heatmap_data[year] = year_data

    return heatmap_data


# Function to generate the bar chart
def generate_bar_chart(
    df: pd.DataFrame, from_date: datetime, to_date: datetime, immersion_type: str = None
) -> io.BytesIO:
    # Apply consistent plot styles
    set_plot_styles()

    df_plot, x_lab, date_labels = process_bar_data(
        df, from_date, to_date, immersion_type
    )

    fig, ax = plt.subplots(figsize=(16, 12))
    fig.patch.set_facecolor("#2c2c2d")
    df_plot.plot(
        kind="bar",
        stacked=True,
        ax=ax,
        color=[MEDIA_TYPES[col].get("color", "gray") for col in df_plot.columns],
    )
    ax.set_title(
        "Total Immersion Time Over Time"
        if not immersion_type
        else f"{MEDIA_TYPES[immersion_type]['log_name']} Over Time"
    )
    ax.set_ylabel(
        "Immersion Time (mins)"
        if not immersion_type
        else MEDIA_TYPES[immersion_type]["unit_name"] + "s"
    )
    ax.set_xlabel("Date" + x_lab)
    ax.set_xticklabels(date_labels, rotation=45, ha="right")
    ax.grid(color="#8b8c8c", axis="y")
    # remove splines
    for spline in ax.spines.values():
        if spline.spine_type != "bottom":
            spline.set_visible(False)

    buffer = io.BytesIO()
    plt.savefig(
        buffer, format="png", facecolor=fig.get_facecolor(), bbox_inches="tight"
    )
    buffer.seek(0)

    return buffer


# Function to generate the heatmap
def generate_heatmap(
    df: pd.DataFrame, from_date: datetime, to_date: datetime, immersion_type
) -> io.BytesIO:
    set_plot_styles()
    heatmap_data = process_heatmap_data(df, from_date, to_date)
    cmap = modify_cmap("Blues_r", zero_color="#222222", nan_color="#2c2c2d")

    num_years = len(heatmap_data)
    fig_height = num_years * 3
    fig, axes = plt.subplots(nrows=num_years, ncols=1, figsize=(18, fig_height))
    fig.patch.set_facecolor("#303446")

    if num_years == 1:
        axes = [axes]

    current_date = datetime.now().date()
    for ax, (year, data) in zip(axes, heatmap_data.items()):
        sns.heatmap(
            data,
            cmap=cmap,
            linewidths=1.5,
            linecolor="#2c2c2d",
            cbar=False,
            square=True,
            ax=ax,
        )
        # ax.set_title(f"Heatmap - {year}")
        ax.set_title(
            f"{MEDIA_TYPES[immersion_type]['Achievement_Group']} Heatmap - {year}"
            if immersion_type
            else f"Immersion Heatmap - {year}"
        )
        ax.axis("off")
        # add a colorbar for the heatmap
        cbar = fig.colorbar(
            ax.collections[0],
            ax=ax,
            orientation="horizontal",
            fraction=0.1,
            pad=0.02,
            aspect=50,
        )
        cbar.ax.yaxis.set_tick_params(color="#c6d0f5")
        cbar.outline.set_edgecolor("#222222")
        plt.setp(plt.getp(cbar.ax.axes, "yticklabels"), color="#c6d0f5")
        # Highlight the current day with a dark border
        if current_date.year == year:
            current_week = current_date.isocalendar().week - 1
            current_day = current_date.weekday()
            rect = patches.Rectangle(
                (current_week, current_day),
                1,
                1,
                linewidth=2,
                edgecolor="black",
                facecolor="none",
            )
            ax.add_patch(rect)

    plt.tight_layout(pad=2.0)

    buffer = io.BytesIO()
    plt.savefig(
        buffer, format="png", facecolor=fig.get_facecolor(), bbox_inches="tight"
    )
    buffer.seek(0)

    return buffer


def generate_wrapped_image(
    user_name: str,
    from_date: datetime,
    to_date: datetime,
    total_time: float,
    top_category: Optional[dict],
    most_logged_item: Optional[dict],
    avg_daily_time: float,
    total_days_in_period: int,
    days_with_logs_percentage: float,
    logged_days: int,
    longest_streak: int,
    category_stats: pd.DataFrame,
    immersion_type: Optional[str] = None,
    avatar_url: Optional[str] = None,
) -> io.BytesIO:
    """Generate a beautiful infographic-style image with immersion stats."""
    set_plot_styles()

    fig = plt.figure(figsize=(16, 12), facecolor="#303446")
    # Increased top padding to create more space between title and boxes (doubled padding)
    gs = fig.add_gridspec(
        3, 3, hspace=0.15, wspace=0.15, left=0.05, right=0.93, top=0.82, bottom=0.05
    )

    # Get font properties for consistent rendering (including numbers)
    font_prop = fm.FontProperties(family=plt.rcParams["font.family"])

    year = from_date.year
    title_text = f"{user_name} Year in Immersion ({year})"
    if immersion_type:
        title_text += f" - {MEDIA_TYPES[immersion_type]['log_name']}"

    # Wrap title if it's too long to prevent clipping (wrap to fit available width)
    wrapped_title = textwrap.fill(title_text, width=32)

    # Position title centered, accounting for avatar on the left
    # Adjust y position based on number of lines and padding
    title_lines = wrapped_title.count("\n") + 1
    # Start higher if multiple lines to keep it visually centered
    title_y = 0.95 if title_lines == 1 else 0.96

    # Center align the title (accounting for avatar on left, so center in available space)
    # Avatar is at 0.05-0.17, so center the text in the remaining space (0.17 to 0.95)
    # Center point would be around (0.17 + 0.95) / 2 = 0.56, but let's use 0.5 for overall figure center
    fig.text(
        0.54,
        title_y,
        wrapped_title,
        fontsize=42,
        fontweight="bold",
        color="#c6d0f5",
        ha="center",
        va="top",
        fontproperties=font_prop,
    )

    # Add avatar if available
    if avatar_url:
        try:
            response = requests.get(avatar_url, timeout=5)
            if response.status_code == 200:
                avatar_img = Image.open(io.BytesIO(response.content))
                if avatar_img.mode in ("RGBA", "LA", "P"):
                    background = Image.new("RGB", avatar_img.size, (48, 52, 70))
                    if avatar_img.mode == "P":
                        avatar_img = avatar_img.convert("RGBA")
                    elif avatar_img.mode == "LA":
                        avatar_img = avatar_img.convert("RGBA")
                    background.paste(
                        avatar_img,
                        mask=avatar_img.split()[-1]
                        if avatar_img.mode == "RGBA"
                        else None,
                    )
                    avatar_img = background
                elif avatar_img.mode != "RGB":
                    avatar_img = avatar_img.convert("RGB")

                # Create circular mask
                size = 140
                mask = Image.new("L", (size, size), 0)
                from PIL import ImageDraw

                ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)

                # Resize and apply mask
                avatar_img = avatar_img.resize((size, size), Image.Resampling.LANCZOS)
                avatar_img.putalpha(mask)

                # Place avatar on the left side of the title
                ax_avatar = fig.add_axes([0.05, 0.90, 0.12, 0.12])
                ax_avatar.imshow(avatar_img)
                ax_avatar.axis("off")

                # Add circular border
                border = patches.Circle(
                    (0.5, 0.5),
                    0.48,
                    transform=ax_avatar.transAxes,
                    fill=False,
                    edgecolor="#7287fd",
                    linewidth=3,
                )
                ax_avatar.add_patch(border)
        except Exception:
            # If avatar loading fails, just continue without it
            pass

    def create_stat_box(ax, title, value, subtitle="", color="#7287fd"):
        ax.axis("off")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)

        # Background rectangle
        rect = patches.Rectangle(
            (0, 0),
            1,
            1,
            linewidth=2,
            edgecolor=color,
            facecolor="#232634",
            transform=ax.transAxes,
        )
        ax.add_patch(rect)

        # Title
        ax.text(
            0.5,
            0.75,
            title,
            fontsize=18,
            fontweight="bold",
            color="#8b8c8c",
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontproperties=font_prop,
        )

        # Value
        ax.text(
            0.5,
            0.45,
            value,
            fontsize=32,
            fontweight="bold",
            color=color,
            ha="center",
            va="center",
            transform=ax.transAxes,
            fontproperties=font_prop,
        )

        # Subtitle
        if subtitle:
            ax.text(
                0.5,
                0.15,
                subtitle,
                fontsize=14,
                color="#c6d0f5",
                ha="center",
                va="center",
                transform=ax.transAxes,
                fontproperties=font_prop,
            )

    hours = int(total_time // 60)
    minutes = int(total_time % 60)
    time_str = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
    ax1 = fig.add_subplot(gs[0, 0])
    create_stat_box(
        ax1, "⏱️ Total Time", time_str, f"{total_time:.1f} minutes", "#7287fd"
    )

    if top_category is not None:
        category_name = top_category["media_type"]
        category_time = top_category["time_logged"]
        category_amount = top_category["amount_logged"]
        unit_name = MEDIA_TYPES[category_name]["unit_name"]
        category_hours = int(category_time // 60)
        category_minutes = int(category_time % 60)
        category_time_str = (
            f"{category_hours}h {category_minutes}m"
            if category_hours > 0
            else f"{category_minutes}m"
        )
        category_color = MEDIA_TYPES[category_name].get("color", "#7287fd")

        ax2 = fig.add_subplot(gs[0, 1])
        create_stat_box(
            ax2,
            "🏆 Top Category",
            category_name,
            f"{category_time_str} • {category_amount:.0f} {unit_name}{'s' if category_amount > 1 else ''}",
            category_color,
        )

    if most_logged_item is not None and most_logged_item.get("media_name"):
        item_name = most_logged_item["media_name"]
        item_entries = most_logged_item["entry_count"]
        item_time = most_logged_item["time_logged"]
        item_hours = int(item_time // 60)
        item_minutes = int(item_time % 60)
        item_time_str = (
            f"{item_hours}h {item_minutes}m" if item_hours > 0 else f"{item_minutes}m"
        )

        ax3 = fig.add_subplot(gs[0, 2])
        ax3.axis("off")
        ax3.set_xlim(0, 1)
        ax3.set_ylim(0, 1)

        rect = patches.Rectangle(
            (0, 0),
            1,
            1,
            linewidth=2,
            edgecolor="#ef9f76",
            facecolor="#232634",
            transform=ax3.transAxes,
        )
        ax3.add_patch(rect)

        ax3.text(
            0.5,
            0.75,
            "📚 Most Logged",
            fontsize=18,
            fontweight="bold",
            color="#8b8c8c",
            ha="center",
            va="center",
            transform=ax3.transAxes,
            fontproperties=font_prop,
        )

        wrapped_item_name = textwrap.fill(item_name, width=20)
        lines = wrapped_item_name.split("\n")
        num_lines = len(lines)
        line_height = 0.09
        total_height = num_lines * line_height
        start_y = 0.45 + (total_height / 2) - (line_height / 2)

        for i, line in enumerate(lines):
            y_pos = start_y - (i * line_height)
            ax3.text(
                0.5,
                y_pos,
                line,
                fontsize=20,
                fontweight="bold",
                color="#ef9f76",
                ha="center",
                va="center",
                transform=ax3.transAxes,
                fontproperties=font_prop,
            )

        ax3.text(
            0.5,
            0.15,
            f"{item_entries} log{'s' if item_entries > 1 else ''} • {item_time_str}",
            fontsize=14,
            color="#c6d0f5",
            ha="center",
            va="center",
            transform=ax3.transAxes,
            fontproperties=font_prop,
        )

    avg_hours = int(avg_daily_time // 60)
    avg_minutes = int(avg_daily_time % 60)
    avg_time_str = (
        f"{avg_hours}h {avg_minutes}m" if avg_hours > 0 else f"{avg_minutes}m"
    )
    ax4 = fig.add_subplot(gs[1, 0])
    create_stat_box(
        ax4,
        "📈 Daily Average",
        avg_time_str,
        f"{avg_daily_time:.1f} min/day",
        "#a6d189",
    )

    ax5 = fig.add_subplot(gs[1, 1])
    create_stat_box(
        ax5,
        "📆 Consistency",
        f"{days_with_logs_percentage:.1f}%",
        f"{logged_days} of {total_days_in_period} days",
        "#e78284",
    )

    ax6 = fig.add_subplot(gs[1, 2])
    create_stat_box(
        ax6,
        "🔥 Longest Streak",
        f"{longest_streak} days",
        "Consecutive days logged",
        "#f2d5cf",
    )

    if len(category_stats) > 0:
        # Breakdown section (left side)
        ax7 = fig.add_subplot(gs[2, :2])
        ax7.axis("off")
        ax7.set_xlim(0, 1)
        ax7.set_ylim(0, 1)

        # Title
        ax7.text(
            0.5,
            0.95,
            "📋 Category Breakdown",
            fontsize=24,
            fontweight="bold",
            color="#c6d0f5",
            ha="center",
            transform=ax7.transAxes,
            fontproperties=font_prop,
        )

        # Create breakdown text
        total_time_for_pct = category_stats["time_logged"].sum()
        for idx, (_, row) in enumerate(category_stats.head(6).iterrows()):
            cat_name = row["media_type"]
            cat_time = row["time_logged"]
            cat_amount = row["amount_logged"]
            unit_name = MEDIA_TYPES[cat_name]["unit_name"]
            percentage = (
                (cat_time / total_time_for_pct * 100) if total_time_for_pct > 0 else 0
            )
            cat_color = MEDIA_TYPES[cat_name].get("color", "#7287fd")

            col = idx % 2
            row_pos = idx // 2
            x_pos = 0.05 + col * 0.48
            y_pos = 0.75 - row_pos * 0.28

            # Category name with color
            ax7.text(
                x_pos,
                y_pos + 0.08,
                cat_name,
                fontsize=18,
                fontweight="bold",
                color=cat_color,
                ha="left",
                transform=ax7.transAxes,
                fontproperties=font_prop,
            )

            # Stats
            stats_text = f"{cat_time:.1f} min ({percentage:.1f}%) • {cat_amount:.0f} {unit_name}{'s' if cat_amount > 1 else ''}"
            ax7.text(
                x_pos,
                y_pos,
                stats_text,
                fontsize=14,
                color="#8b8c8c",
                ha="left",
                transform=ax7.transAxes,
                fontproperties=font_prop,
            )

        # Pie chart section (right side)
        ax8 = fig.add_subplot(gs[2, 2])
        ax8.set_facecolor("#232634")

        # Prepare pie chart data - sort by size to get top categories
        sorted_stats = category_stats.sort_values("time_logged", ascending=False)
        pie_labels = sorted_stats["media_type"].tolist()
        pie_sizes = sorted_stats["time_logged"].tolist()
        pie_colors = [MEDIA_TYPES[cat].get("color", "#7287fd") for cat in pie_labels]

        # Only show labels for top 3 categories, others will be empty strings
        pie_labels_display = []
        for i, label in enumerate(pie_labels):
            if i < 3:
                pie_labels_display.append(label)
            else:
                pie_labels_display.append("")  # Hide label for small slices

        # Create pie chart
        wedges, texts, autotexts = ax8.pie(
            pie_sizes,
            labels=pie_labels_display,
            colors=pie_colors,
            autopct="%1.1f%%",
            startangle=90,
            textprops={"fontsize": 10, "color": "#c6d0f5", "fontproperties": font_prop},
        )

        # Style the pie chart - only show percentage and labels for top 3
        for i, autotext in enumerate(autotexts):
            if i >= 3:
                autotext.set_text("")  # Hide percentage for small slices
            else:
                autotext.set_color("#c6d0f5")
                autotext.set_fontweight("bold")
                autotext.set_fontproperties(font_prop)

        for i, text in enumerate(texts):
            if i < 3:
                text.set_fontproperties(font_prop)
                text.set_fontsize(11)
            else:
                text.set_text("")  # Hide label text for small slices

        ax8.set_title(
            "",
            fontsize=18,
            fontweight="bold",
            color="#c6d0f5",
            pad=10,
            fontproperties=font_prop,
        )

    buffer = io.BytesIO()
    plt.savefig(
        buffer,
        format="png",
        facecolor=fig.get_facecolor(),
        bbox_inches="tight",
        dpi=150,
    )
    buffer.seek(0)
    plt.close(fig)

    return buffer


class ImmersionLogMe(commands.Cog):
    def __init__(self, bot: JouzuBot):
        self.bot = bot

    async def get_user_logs(self, user_id, from_date, to_date, immersion_type=None):
        if immersion_type:
            query = GET_USER_LOGS_FOR_PERIOD_QUERY_WITH_MEDIA_TYPE
            params = (
                user_id,
                from_date.strftime("%Y-%m-%d %H:%M:%S"),
                to_date.strftime("%Y-%m-%d %H:%M:%S"),
                immersion_type,
            )
        else:
            query = GET_USER_LOGS_FOR_PERIOD_QUERY_BASE
            params = (
                user_id,
                from_date.strftime("%Y-%m-%d %H:%M:%S"),
                to_date.strftime("%Y-%m-%d %H:%M:%S"),
            )

        user_logs = await self.bot.GET(query, params)
        return user_logs

    async def get_user_logs_with_name(
        self, user_id, from_date, to_date, immersion_type=None
    ):
        if immersion_type:
            query = GET_USER_LOGS_FOR_PERIOD_WITH_NAME_QUERY_WITH_MEDIA_TYPE
            params = (
                user_id,
                from_date.strftime("%Y-%m-%d %H:%M:%S"),
                to_date.strftime("%Y-%m-%d %H:%M:%S"),
                immersion_type,
            )
        else:
            query = GET_USER_LOGS_FOR_PERIOD_WITH_NAME_QUERY_BASE
            params = (
                user_id,
                from_date.strftime("%Y-%m-%d %H:%M:%S"),
                to_date.strftime("%Y-%m-%d %H:%M:%S"),
            )

        user_logs = await self.bot.GET(query, params)
        return user_logs

    async def fetch_title_from_api(
        self, media_type: str, media_id: str
    ) -> Optional[str]:
        class MockInteraction:
            def __init__(self, media_type_str):
                self.namespace = {"media_type": media_type_str}

        if media_type == "Visual Novel":
            mock_interaction = MockInteraction("Visual Novel")
            choices = await query_vndb(mock_interaction, media_id, self.bot)
            if choices:
                vndb_id = media_id if media_id.startswith("v") else f"v{media_id}"
                result = await self.bot.GET_ONE(CACHED_VNDB_TITLE_QUERY, (vndb_id,))
                if result and result[0]:
                    return result[0]
            return None

        elif media_type in ["Anime", "Manga"]:
            mock_interaction = MockInteraction(
                "Anime" if media_type == "Anime" else "Reading"
            )
            choices = await query_anilist(mock_interaction, media_id, self.bot)
            if choices:
                result = await self.bot.GET_ONE(
                    CACHED_ANILIST_TITLE_QUERY, (int(media_id),)
                )
                if result and result[0]:
                    return result[0]
            return None

        return None

    @discord.app_commands.command(
        name="log_stats", description="Display an immersion overview with a specified."
    )
    @discord.app_commands.describe(
        user="Optional user to display the immersion overview for.",
        from_date="Optional start date (YYYY-MM-DD).",
        to_date="Optional end date (YYYY-MM-DD).",
        immersion_type="Optional type of immersion to filter by (e.g., reading, listening, etc.).",
    )
    @discord.app_commands.choices(immersion_type=LOG_CHOICES)
    async def log_stats(
        self,
        interaction: discord.Interaction,
        user: Optional[discord.User] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        immersion_type: Optional[str] = None,
    ):
        await interaction.response.defer()

        member = user if user else interaction.user
        user_id = member.id
        guild_id = interaction.guild_id
        if guild_id != None:
            nick_name, user_name = await get_username_db(self.bot, guild_id, member)
        else:
            nick_name, user_name = member.name, member.name

        try:
            if from_date:
                from_date = datetime.strptime(from_date, "%Y-%m-%d")
                start_of_year = datetime(from_date.year, 1, 1)
            else:
                now = datetime.now()
                from_date = now.replace(day=1, hour=0, minute=0, second=0)
                start_of_year = datetime(now.year, 1, 1, 0, 0, 0)
        except ValueError:
            return await interaction.followup.send(
                "Invalid from_date format. Please use YYYY-MM-DD.", ephemeral=True
            )

        try:
            to_date = (
                datetime.strptime(to_date, "%Y-%m-%d") if to_date else datetime.now()
            )
            to_date = to_date.replace(hour=23, minute=59, second=59)
        except ValueError:
            return await interaction.followup.send(
                "Invalid to_date format. Please use YYYY-MM-DD.", ephemeral=True
            )

        user_logs = await self.get_user_logs(
            user_id, start_of_year, to_date, immersion_type
        )
        logs_df = pd.DataFrame(
            user_logs,
            columns=["media_type", "amount_logged", "time_logged", "log_date"],
        )
        logs_df["log_date"] = pd.to_datetime(logs_df["log_date"])
        logs_df = logs_df.set_index("log_date")

        if logs_df[from_date:to_date].empty:
            return await interaction.followup.send(
                "No logs found for the specified period. Did you forget to enter a time period?",
                ephemeral=True,
            )
        figure_buffer_bar = await asyncio.to_thread(
            generate_bar_chart, logs_df, from_date, to_date, immersion_type
        )
        figure_buffer_heatmap = await asyncio.to_thread(
            generate_heatmap, logs_df, from_date, to_date, immersion_type
        )

        breakdown_str, time_total = await asyncio.to_thread(
            embedded_info, logs_df[from_date:to_date]
        )
        timeframe_str = (
            f"{from_date.strftime('%Y-%m-%d')} to {to_date.strftime('%Y-%m-%d')}"
        )

        embed = discord.Embed(title="Immersion Overview", color=discord.Color.blurple())
        embed.add_field(
            name="User", value=nick_name if nick_name else user_name, inline=True
        )
        embed.add_field(name="Timeframe", value=timeframe_str, inline=True)
        embed.add_field(
            name="Immersion Time", value=f"{time_total:.2f} minutes", inline=True
        )
        if immersion_type:
            embed.add_field(
                name="Immersion Type", value=immersion_type.capitalize(), inline=True
            )
        embed.add_field(name="Breakdown", value=breakdown_str, inline=False)

        file_bar = discord.File(figure_buffer_bar, filename="bar_chart.png")
        file_heatmap = discord.File(figure_buffer_heatmap, filename="heatmap.png")
        embed.set_image(url="attachment://bar_chart.png")

        await interaction.followup.send(file=file_bar, embed=embed)
        await interaction.followup.send(file=file_heatmap)

    @discord.app_commands.command(
        name="log_wrapped", description="Your year in immersion stats!"
    )
    @discord.app_commands.describe(
        user="Optional user to display the immersion summary for.",
        from_date="Optional start date (YYYY-MM-DD). Defaults to the beginning of the year.",
        to_date="Optional end date (YYYY-MM-DD).",
        immersion_type="Optional type of immersion to filter by (e.g., reading, listening, etc.).",
    )
    @discord.app_commands.choices(immersion_type=LOG_CHOICES)
    async def log_wrapped(
        self,
        interaction: discord.Interaction,
        user: Optional[discord.User] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        immersion_type: Optional[str] = None,
    ):
        await interaction.response.defer()

        member = user if user else interaction.user
        user_id = member.id
        guild_id = interaction.guild_id
        if guild_id != None:
            nick_name, user_name = await get_username_db(self.bot, guild_id, member)
        else:
            nick_name, user_name = member.name, member.name

        try:
            if from_date:
                from_date = datetime.strptime(from_date, "%Y-%m-%d")
            else:
                now = datetime.now()
                from_date = datetime(now.year, 1, 1, 0, 0, 0)
        except ValueError:
            return await interaction.followup.send(
                "Invalid from_date format. Please use YYYY-MM-DD.", ephemeral=True
            )

        try:
            to_date = (
                datetime.strptime(to_date, "%Y-%m-%d") if to_date else datetime.now()
            )
            to_date = to_date.replace(hour=23, minute=59, second=59)
        except ValueError:
            return await interaction.followup.send(
                "Invalid to_date format. Please use YYYY-MM-DD.", ephemeral=True
            )

        user_logs = await self.get_user_logs_with_name(
            user_id, from_date, to_date, immersion_type
        )
        logs_df = pd.DataFrame(
            user_logs,
            columns=[
                "media_type",
                "media_name",
                "amount_logged",
                "time_logged",
                "log_date",
            ],
        )
        logs_df["log_date"] = pd.to_datetime(logs_df["log_date"])
        logs_df = logs_df.set_index("log_date")

        if logs_df[from_date:to_date].empty:
            return await interaction.followup.send(
                "No logs found for the specified period. Did you forget to enter a time period?",
                ephemeral=True,
            )

        period_df = logs_df[from_date:to_date].copy()

        total_time = period_df["time_logged"].sum()

        category_stats = (
            period_df.groupby("media_type")
            .agg({"time_logged": "sum", "amount_logged": "sum"})
            .reset_index()
        )
        category_stats = category_stats.sort_values("time_logged", ascending=False)
        top_category = category_stats.iloc[0] if not category_stats.empty else None

        if not period_df["media_name"].isna().all():
            item_stats = (
                period_df[period_df["media_name"].notna()]
                .groupby("media_name")
                .agg({"amount_logged": "sum", "time_logged": "sum"})
            )
            item_stats["entry_count"] = (
                period_df[period_df["media_name"].notna()].groupby("media_name").size()
            )
            item_stats = item_stats.reset_index()
            most_logged_item = (
                item_stats.sort_values("time_logged", ascending=False).iloc[0]
                if not item_stats.empty
                else None
            )

            if most_logged_item is not None:
                media_name = most_logged_item["media_name"]
                media_type_row = period_df[period_df["media_name"] == media_name].iloc[
                    0
                ]
                media_type = media_type_row["media_type"]
                most_logged_item["media_type"] = media_type

                if media_type in ["Visual Novel", "Anime", "Manga", "Reading"]:
                    if media_type == "Visual Novel":
                        needs_title_lookup = (
                            media_name.startswith("v") and media_name[1:].isdigit()
                        ) or media_name.isdigit()
                    else:
                        needs_title_lookup = media_name.isdigit()

                    if needs_title_lookup:
                        title = None
                        if MEDIA_TYPES[media_type]["title_query"]:
                            title_result = await self.bot.GET(
                                MEDIA_TYPES[media_type]["title_query"], (media_name,)
                            )
                            if title_result and title_result[0] and title_result[0][0]:
                                title = title_result[0][0]

                        if not title:
                            title = await self.fetch_title_from_api(
                                media_type, media_name
                            )

                        if title:
                            most_logged_item["media_name"] = title
        else:
            most_logged_item = None

        total_days_in_period = (to_date.date() - from_date.date()).days + 1
        avg_daily_time = (
            total_time / total_days_in_period if total_days_in_period > 0 else 0
        )

        logged_days = len(np.unique(period_df.index.date))
        days_with_logs_percentage = (
            (logged_days / total_days_in_period * 100)
            if total_days_in_period > 0
            else 0
        )

        logged_dates = sorted(set(period_df.index.date))
        longest_streak = 0
        current_streak = 0
        prev_date = None

        for date in logged_dates:
            if prev_date is None:
                current_streak = 1
            elif (date - prev_date).days == 1:
                current_streak += 1
            else:
                longest_streak = max(longest_streak, current_streak)
                current_streak = 1
            prev_date = date

        longest_streak = max(longest_streak, current_streak)
        embed = discord.Embed(
            title="📊 Immersion Summary",
            description=f"**{nick_name if nick_name else user_name}**'s immersion stats",
            color=discord.Color.blurple(),
        )

        timeframe_str = (
            f"{from_date.strftime('%Y-%m-%d')} to {to_date.strftime('%Y-%m-%d')}"
        )
        embed.add_field(name="📅 Timeframe", value=timeframe_str, inline=False)

        hours = int(total_time // 60)
        minutes = int(total_time % 60)
        time_str = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
        embed.add_field(
            name="⏱️ Total Time Immersed",
            value=f"**{time_str}** ({total_time:.1f} minutes)",
            inline=True,
        )

        if top_category is not None:
            category_name = top_category["media_type"]
            category_time = top_category["time_logged"]
            category_amount = top_category["amount_logged"]
            unit_name = MEDIA_TYPES[category_name]["unit_name"]
            category_hours = int(category_time // 60)
            category_minutes = int(category_time % 60)
            category_time_str = (
                f"{category_hours}h {category_minutes}m"
                if category_hours > 0
                else f"{category_minutes}m"
            )

            embed.add_field(
                name="🏆 Top Category",
                value=f"**{category_name}**\n{category_time_str} ({category_time:.1f} min)\n{category_amount:.0f} {unit_name}{'s' if category_amount > 1 else ''}",
                inline=True,
            )

        if most_logged_item is not None and most_logged_item["media_name"]:
            item_name = most_logged_item["media_name"]
            item_entries = most_logged_item["entry_count"]
            item_time = most_logged_item["time_logged"]
            item_hours = int(item_time // 60)
            item_minutes = int(item_time % 60)
            item_time_str = (
                f"{item_hours}h {item_minutes}m"
                if item_hours > 0
                else f"{item_minutes}m"
            )

            embed.add_field(
                name="📚 Most Logged Item",
                value=f"**{item_name}**\n{item_entries} log{'s' if item_entries > 1 else ''}\n{item_time_str} total",
                inline=True,
            )

        avg_hours = int(avg_daily_time // 60)
        avg_minutes = int(avg_daily_time % 60)
        avg_time_str = (
            f"{avg_hours}h {avg_minutes}m" if avg_hours > 0 else f"{avg_minutes}m"
        )
        embed.add_field(
            name="📈 Average Daily Time",
            value=f"**{avg_time_str}**\n({avg_daily_time:.1f} min/day)\nOver {total_days_in_period} day{'s' if total_days_in_period > 1 else ''}",
            inline=True,
        )

        embed.add_field(
            name="📆 Logging Consistency",
            value=f"**{days_with_logs_percentage:.1f}%**\n{logged_days} of {total_days_in_period} day{'s' if total_days_in_period > 1 else ''} logged",
            inline=True,
        )

        embed.add_field(
            name="🔥 Longest Streak",
            value=f"**{longest_streak} day{'s' if longest_streak > 1 else ''}**\nConsecutive days with logs",
            inline=True,
        )

        if len(category_stats) > 1:
            breakdown_lines = []
            for _, row in category_stats.head(5).iterrows():
                cat_name = row["media_type"]
                cat_time = row["time_logged"]
                cat_amount = row["amount_logged"]
                unit_name = MEDIA_TYPES[cat_name]["unit_name"]
                percentage = (cat_time / total_time * 100) if total_time > 0 else 0
                breakdown_lines.append(
                    f"• **{cat_name}**: {cat_time:.1f} min ({percentage:.1f}%) - {cat_amount:.0f} {unit_name}{'s' if cat_amount > 1 else ''}"
                )

            embed.add_field(
                name="📋 Category Breakdown",
                value="\n".join(breakdown_lines),
                inline=False,
            )

        if immersion_type:
            embed.set_footer(text=f"Filtered by: {immersion_type}")

        display_name = nick_name if nick_name else user_name
        top_category_dict = dict(top_category) if top_category is not None else None
        most_logged_dict = (
            dict(most_logged_item) if most_logged_item is not None else None
        )
        avatar_url = str(member.display_avatar.url) if member else None

        figure_buffer = await asyncio.to_thread(
            generate_wrapped_image,
            display_name,
            from_date,
            to_date,
            total_time,
            top_category_dict,
            most_logged_dict,
            avg_daily_time,
            total_days_in_period,
            days_with_logs_percentage,
            logged_days,
            longest_streak,
            category_stats,
            immersion_type,
            avatar_url,
        )

        figure_buffer_heatmap = await asyncio.to_thread(
            generate_heatmap, logs_df, from_date, to_date, immersion_type
        )

        file_image = discord.File(figure_buffer, filename="immersion_wrapped.png")
        embed.set_image(url="attachment://immersion_wrapped.png")

        await interaction.followup.send(file=file_image, embed=embed)

        file_heatmap = discord.File(figure_buffer_heatmap, filename="heatmap.png")
        await interaction.followup.send(file=file_heatmap)


async def setup(bot):
    await bot.add_cog(ImmersionLogMe(bot))

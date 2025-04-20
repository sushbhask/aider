from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt
import yaml
from imgcat import imgcat
from matplotlib import rc
from treebeardhq import Log



@dataclass
class ModelData:
    name: str
    release_date: date
    pass_rate: float

    @property
    def color(self) -> str:
        model = self.name.lower()
        if "gemini" in model and "pro" in model:
            return "magenta"
        if "qwen" in model:
            return "darkblue"
        if "mistral" in model:
            return "cyan"
        if "haiku" in model:
            return "pink"
        if "deepseek" in model:
            return "brown"
        if "sonnet" in model:
            return "orange"
        if "-4o" in model:
            return "purple"
        if "gpt-4" in model:
            return "red"
        if "gpt-3.5" in model:
            return "green"
        return "lightblue"

    @property
    def legend_label(self) -> str:
        model = self.name.lower()
        if "gemini" in model and "pro" in model:
            return "Gemini 1.5 Pro"
        if "claude-3-sonnet" in model:
            return "Sonnet"
        if "o1-preview" in model:
            return "O1 Preview"
        if "gpt-3.5" in model:
            return "GPT-3.5 Turbo"
        if "gpt-4-" in model and "-4o" not in model:
            return "GPT-4"
        if "qwen" in model:
            return "Qwen"
        if "-4o" in model:
            return "GPT-4o"
        if "haiku" in model:
            return "Haiku"
        if "deepseek" in model:
            return "DeepSeek"
        if "mistral" in model:
            return "Mistral"
        return model


class BenchmarkPlotter:
    LABEL_FONT_SIZE = 16

    def __init__(self):
        self.setup_plot_style()

    def setup_plot_style(self):
        plt.rcParams["hatch.linewidth"] = 0.5
        plt.rcParams["hatch.color"] = "#444444"
        rc("font", **{"family": "sans-serif", "sans-serif": ["Helvetica"], "size": 10})
        plt.rcParams["text.color"] = "#444444"

    def load_data(self, yaml_file: str) -> List[ModelData]:
        Log.info("Loading model data from YAML file", yaml_file=yaml_file)
        try:
            with open(yaml_file, "r") as file:
                data = yaml.safe_load(file)
        except Exception as e:
            Log.error("Failed to load or parse YAML file", error=e, file_path=yaml_file)
            raise

        models = []
        for entry in data:
            if "released" in entry and "pass_rate_2" in entry:
                model = ModelData(
                    name=entry["model"].split("(")[0].strip(),
                    release_date=entry["released"],
                    pass_rate=entry["pass_rate_2"],
                )
                models.append(model)
        
        Log.debug("Finished loading model data", model_count=len(models))
        return models

    def create_figure(self) -> Tuple[plt.Figure, plt.Axes]:
        fig, ax = plt.subplots(figsize=(12, 8))
        ax.grid(axis="y", zorder=0, lw=0.2)
        for spine in ax.spines.values():
            spine.set_edgecolor("#DDDDDD")
            spine.set_linewidth(0.5)
        return fig, ax

    def plot_model_series(self, ax: plt.Axes, models: List[ModelData]):
        Log.info("Plotting model performance series", model_count=len(models))
        # Group models by color
        color_groups: Dict[str, List[ModelData]] = {}
        for model in models:
            if model.color not in color_groups:
                color_groups[model.color] = []
            color_groups[model.color].append(model)
        
        Log.debug("Grouped models by color", group_count=len(color_groups))

        # Plot each color group
        for color, group in color_groups.items():
            sorted_group = sorted(group, key=lambda x: x.release_date)
            dates = [m.release_date for m in sorted_group]
            rates = [m.pass_rate for m in sorted_group]

            # Plot line
            ax.plot(dates, rates, c=color, alpha=0.5, linewidth=1)

            # Plot points
            ax.scatter(dates, rates, c=color, alpha=0.5, s=120)

            # Add label for first point
            first_model = sorted_group[0]
            ax.annotate(
                first_model.legend_label,
                (first_model.release_date, first_model.pass_rate),
                xytext=(10, 5),
                textcoords="offset points",
                color=color,
                alpha=0.8,
                fontsize=self.LABEL_FONT_SIZE,
            )
            
            Log.debug("Plotted model group", color=color, model_count=len(sorted_group), 
                     first_model=first_model.name, first_model_rate=first_model.pass_rate)

        Log.info("Completed plotting all model series", total_models=len(models), group_count=len(color_groups))

    def set_labels_and_style(self, ax: plt.Axes):
        ax.set_xlabel("Model release date", fontsize=18, color="#555")
        ax.set_ylabel(
            "Aider code editing benchmark,\npercent completed correctly", fontsize=18, color="#555"
        )
        ax.set_title("LLM code editing skill by model release date", fontsize=20)
        ax.set_ylim(30, 90)
        plt.xticks(fontsize=14, rotation=45, ha="right")
        plt.tight_layout(pad=1.0)

    def save_and_display(self, fig: plt.Figure):
        Log.info("Saving benchmark plot to files")
        try:
            plt.savefig("aider/website/assets/models-over-time.png")
            plt.savefig("aider/website/assets/models-over-time.svg")
            Log.debug("Successfully saved plot files")
            imgcat(fig)
        except Exception as e:
            Log.error("Error saving plot files", error=e)

    def plot(self, yaml_file: str):
        Log.info("Starting benchmark plotting process", yaml_file=yaml_file)
        models = self.load_data(yaml_file)
        fig, ax = self.create_figure()
        self.plot_model_series(ax, models)
        self.set_labels_and_style(ax)
        self.save_and_display(fig)
        Log.info("Benchmark plotting completed", model_count=len(models))


def main():
    Log.info("Starting benchmark plotter")
    plotter = BenchmarkPlotter()
    models = plotter.load_data("aider/website/_data/edit_leaderboard.yml")

    # Print release dates and model names
    for model in sorted(models, key=lambda x: x.release_date):
        print(f"{model.release_date}: {model.name}")

    plotter.plot("aider/website/_data/edit_leaderboard.yml")
    Log.info("Benchmark plotting completed")


if __name__ == "__main__":
    main()

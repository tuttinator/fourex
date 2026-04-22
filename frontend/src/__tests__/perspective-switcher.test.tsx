import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { PerspectiveSwitcher } from "@/components/perspective-switcher";

describe("PerspectiveSwitcher", () => {
	afterEach(() => cleanup());
	it("renders God mode + one pill per player", () => {
		render(
			<PerspectiveSwitcher
				players={["alice", "bob"]}
				perspective={null}
				onPerspectiveChange={() => {}}
			/>,
		);

		expect(screen.getByRole("radio", { name: /god mode/i })).toBeInTheDocument();
		expect(screen.getByRole("radio", { name: /alice/i })).toBeInTheDocument();
		expect(screen.getByRole("radio", { name: /bob/i })).toBeInTheDocument();
	});

	it("marks the current perspective as aria-checked", () => {
		render(
			<PerspectiveSwitcher
				players={["alice", "bob"]}
				perspective="alice"
				onPerspectiveChange={() => {}}
			/>,
		);

		expect(screen.getByRole("radio", { name: /alice/i })).toHaveAttribute(
			"aria-checked",
			"true",
		);
		expect(screen.getByRole("radio", { name: /god mode/i })).toHaveAttribute(
			"aria-checked",
			"false",
		);
	});

	it("fires onPerspectiveChange with the clicked player", () => {
		const onChange = vi.fn();
		render(
			<PerspectiveSwitcher
				players={["alice", "bob"]}
				perspective={null}
				onPerspectiveChange={onChange}
			/>,
		);

		fireEvent.click(screen.getByRole("radio", { name: /bob/i }));
		expect(onChange).toHaveBeenCalledWith("bob");
	});

	it("fires onPerspectiveChange(null) when God mode is clicked", () => {
		const onChange = vi.fn();
		render(
			<PerspectiveSwitcher
				players={["alice", "bob"]}
				perspective="alice"
				onPerspectiveChange={onChange}
			/>,
		);

		fireEvent.click(screen.getByRole("radio", { name: /god mode/i }));
		expect(onChange).toHaveBeenCalledWith(null);
	});

	it("hides the God mode pill when allowGodMode is false", () => {
		render(
			<PerspectiveSwitcher
				players={["alice"]}
				perspective="alice"
				onPerspectiveChange={() => {}}
				allowGodMode={false}
			/>,
		);

		expect(screen.queryByRole("radio", { name: /god mode/i })).toBeNull();
	});
});

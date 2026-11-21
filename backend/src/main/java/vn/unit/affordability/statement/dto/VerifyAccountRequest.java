package vn.unit.affordability.statement.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class VerifyAccountRequest {

    @NotBlank
    @Size(max = 64)
    private String verifiedBy;

    @NotNull
    private Boolean isVerified;

    private Boolean isHolderMatched;
}
